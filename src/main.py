import argparse
import subprocess
from pathlib import Path
import atexit
import re
from typing import *
from utils import *
import os
import csv
import cv2
import numpy as np
import pyspng
import json
import concurrent.futures
import threading
import shutil

mod_path = Path("./mods").absolute()
map_gen_settings_path = Path("./map-gen-settings.json").absolute()
preview_path = Path("./previews").absolute()
factorio_path = Path("")
factorio_data = Path("./data").absolute()

starting_radius = 128
backside_radius = 160
backside_offset = 120 + backside_radius

copper_burner_weight = np.float32(0.7)
coal_burner_weight = np.float32(1)
stone_burner_weight = np.float32(0.2)

class Zone:
    def __init__(self):
        self.iron_area: int = 0
        self.copper_area: int = 0
        self.coal_area: int = 0
        self.stone_area: int = 0

        self.starting_area_pos: Tuple[int, int] = (0, 0)
        self.iron_coal_distance: float = math.inf
        self.iron_copper_distance: float = math.inf
        self.iron_stone_distance: float = math.inf

        self.coal_lake_distance: float = math.inf

class MapData:
    def __init__(self, seed: int):
        self.seed = seed
        self.backside_zones: Dict[Direction, Zone] = {}

def IsFactorioPathValid(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False

    return True

regex_gen_start = re.compile("^\\s*[\\d|\\.]* Generating map preview: seed=(\\d*)")
regex_report = re.compile("^\\s*[\\d|\\.]* ([\\w|-]*): totalEntityCount=(\\d*)")
regex_goodbye = re.compile("^\\s*[\\d|\\.]* Goodbye")
def RunFactorio(first: int, last: int, size: int, offset: Position, mods: Path, reports: Tuple[str], callback: Callable[[int, int, np.ndarray, Dict[str, int]], None]):
    assert(first % 2 == 0 and last % 2 == 0)

    data_path = factorio_data / f"{threading.get_ident()}"
    os.makedirs(data_path, exist_ok=True)
    with open(data_path / "config.ini", "w") as f:
        f.write(f"[path]\nwrite-data={data_path}{os.sep}")

    process = subprocess.Popen([
        factorio_path,
        "--config", str(data_path / "config.ini"),
        "--map-gen-seed", str(first),
        "--map-gen-seed-max", str(last),
        "--map-gen-settings", str(map_gen_settings_path),
        "--generate-map-preview", str(preview_path) + os.sep,
        "--map-preview-size", str(size),
        "--map-preview-offset", f"{offset.x},{offset.y}",
        "--report-quantities", ",".join(reports),
        "--mod-directory", str(mods)
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    atexit.register(process.terminate)
    
    seed = None
    counts = {}
    i = 0

    while True:
        line = process.stdout.readline().decode()
        if not line:
            break

        match = regex_gen_start.match(line)
        if seed != None and (match != None or regex_goodbye.match(line) != None):
            path = preview_path / f"{seed}.png"
            with open(path, "rb") as f:
                np_img = pyspng.load(f.read())
            img = np.asarray(np_img)
            preview = img[:, :, 0]
            callback(i, seed, preview, counts)
            i += 1
            os.remove(path)

        if match != None:
            seed = int(match.group(1))
            continue

        match = regex_report.match(line)
        if match != None:
            counts[match.group(1)] = int(match.group(2))

def EvalZone(seed: int, preview: np.ndarray, counts, minimum_quantities) -> Zone:
    W, H = preview.shape
    zone = Zone()

    if counts["iron-ore"] < minimum_quantities["iron"] or\
        counts["copper-ore"] < minimum_quantities["copper"] or\
        counts["coal"] < minimum_quantities["coal"] or\
        counts["stone"] < minimum_quantities["stone"]:
        return zone

    zone.iron_area = minimum_quantities["iron"]
    zone.copper_area = minimum_quantities["copper"]
    zone.coal_area = minimum_quantities["coal"]
    zone.stone_area = minimum_quantities["stone"]

    iron_mask = preview[:, :] != np.uint8(0)   # iron
    copper_mask = preview[:, :] != np.uint8(1) # copper
    coal_mask = preview[:, :] != np.uint8(2)   # coal
    stone_mask = preview[:, :] != np.uint8(3)  # stone
    water_mask = preview[:, :] != np.uint8(4)  # water

    copper_dt = cv2.distanceTransform((copper_mask).astype(np.uint8), cv2.DIST_L1, 3)
    coal_dt = cv2.distanceTransform((coal_mask).astype(np.uint8), cv2.DIST_L1, 3)
    stone_dt = cv2.distanceTransform((stone_mask).astype(np.uint8), cv2.DIST_L1, 3)

    weighted_copper = copper_dt * copper_burner_weight
    weighted_coal = coal_dt * coal_burner_weight
    weighted_stone = stone_dt * stone_burner_weight

    sums = weighted_copper + weighted_coal + weighted_stone
    sums += iron_mask.astype(np.uint8) * np.uint8(255)
    min_i = np.argmin(sums)

    x = min_i // W
    y = min_i % W

    zone.starting_area_pos = (x, y)
    zone.iron_copper_distance = weighted_copper[x, y]
    zone.iron_coal_distance = weighted_coal[x, y]
    zone.iron_stone_distance = weighted_stone[x, y]

    coal_dt += water_mask.astype(np.uint8) * np.uint8(255)
    zone.coal_lake_distance = np.min(coal_dt)

    return zone

## maps should be sorted from lowest seed to highest
def EvalBackside(maps: List[MapData], direction: Direction, minimum_quantities):
    def Helper(i: int, seed: int, preview: np.ndarray, counts: Dict[str, int]):
        maps[i].backside_zones[direction] = EvalZone(seed, preview, counts, minimum_quantities["backside"])

    base_offset = Position(backside_offset, 0)
    RunFactorio(maps[0].seed, maps[len(maps) - 1].seed, backside_radius * 2,
                base_offset.rotate(direction), mod_path / "regular-patches", ("iron-ore", "copper-ore", "coal", "stone"), Helper)

def EvalSeeds(first: int, nb: int, minimum_quantities) -> List[MapData]:
    assert(first % 2 == 0 and nb % 2 == 0)
    maps = [MapData(s) for s in range(first, first + nb, 2)]

    EvalBackside(maps, Direction.EAST, minimum_quantities)
    print("east done")
    EvalBackside(maps, Direction.SOUTH, minimum_quantities)
    print("south done")
    EvalBackside(maps, Direction.WEST, minimum_quantities)
    print("west done")
    EvalBackside(maps, Direction.NORTH, minimum_quantities)
    print("north done")

    return maps

def WriteOutput(maps: List[MapData]):
    def ZoneHelper(zone: Zone) -> List[str]:
        out = [
            str(zone.iron_area),
            str(zone.copper_area),
            str(zone.coal_area),
            str(zone.stone_area),
            str(zone.starting_area_pos[0]),
            str(zone.starting_area_pos[1]),
            str(zone.iron_coal_distance),
            str(zone.iron_copper_distance),
            str(zone.iron_stone_distance),
            str(zone.coal_lake_distance),
        ]

        return out

    with open("out.csv", "a", newline='') as file:
        writer = csv.writer(file)

        for map in maps:
            writer.writerow(
                [map.seed] +
                ZoneHelper(map.backside_zones[Direction.EAST]) +
                ZoneHelper(map.backside_zones[Direction.SOUTH]) +
                ZoneHelper(map.backside_zones[Direction.WEST]) +
                ZoneHelper(map.backside_zones[Direction.NORTH])
            )

@timer("main")
def main():
    global factorio_path

    atexit.register(lambda: shutil.rmtree(factorio_data))

    parser = argparse.ArgumentParser(
        prog="Factorio Seed Finder"
    )

    parser.add_argument("-f", "--factorio-path", required=True, type=str)
    parser.add_argument("--minimum-quantities", required=True, type=str)
    parser.add_argument("-s", "--first-seed", required=True, type=int)
    parser.add_argument("--batch-count", required=True, type=int)
    parser.add_argument("--batch-size", default=25000, type=int)
    parser.add_argument("--factorio-instance-count", default=1, type=int)

    args = parser.parse_args()

    factorio_path = Path(args.factorio_path)
    if not IsFactorioPathValid(factorio_path):
        print("The provided path for Factorio is not valid.")
        return
    
    with open(args.minimum_quantities) as f:
        minimum_quantities = json.load(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.factorio_instance_count) as executor:
        futures = [executor.submit(EvalSeeds, s, args.batch_size, minimum_quantities)\
                   for s in range(args.first_seed, args.batch_count*args.batch_size + args.first_seed, args.batch_size)]

        with open("out.csv", "w", newline='') as file:
            writer = csv.writer(file)

            titles = ["seed"]
            for p in ("e_", "s_", "w_", "n_"):
                titles += [
                    f"{p}Fe_area",
                    f"{p}Cu_area",
                    f"{p}C_area",
                    f"{p}S_area",
                    f"{p}starting_area_pos_x",
                    f"{p}starting_area_pos_y",
                    f"{p}Fe_C_d",
                    f"{p}Fe_Cu_d",
                    f"{p}fe_S_d",
                    f"{p}C_lake_d"
                ]
            writer.writerow(titles)

        for future in concurrent.futures.as_completed(futures):
            WriteOutput(future.result())

if __name__ == "__main__":
    main()