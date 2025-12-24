import argparse
import subprocess
from pathlib import Path
import atexit
import re
from typing import *
from utils import *
import os
import cv2
import numpy as np
import pyspng
import json
import multiprocessing as mp
from multiprocessing.sharedctypes import Synchronized
import shutil
import sqlite3
from inputimeout import inputimeout, TimeoutOccurred

root_dir = (Path(os.path.realpath(__file__)) / "../..").absolute()
mod_path = root_dir / "./mods"
map_gen_settings_path = root_dir / "./map-gen-settings.json"
preview_path = root_dir / "./previews"
factorio_data = root_dir / "./data"

starting_radius = 128
backside_radius = 160
backside_offset = 320

copper_burner_weight = np.float16(0.7)
coal_burner_weight = np.float16(1)
stone_burner_weight = np.float16(0.25)

max_seed = 4294967296

class Stop:
    def execute(self, db: sqlite3.Connection, return_queue: mp.JoinableQueue):
        pass

class Commit:
    def execute(self, db: sqlite3.Connection, return_queue: mp.JoinableQueue):
        db.commit()

class Execute:
    def __init__(self, command: str):
        self._command = command

    def execute(self, db: sqlite3.Connection, return_queue: mp.JoinableQueue):
        db.execute(self._command)

class LastSeedHelper:
    def execute(self, db: sqlite3.Connection, return_queue: mp.JoinableQueue):
        last_seed_ex = db.execute("""
        SELECT last_seed FROM progress WHERE id=1
        """).fetchone()
        if last_seed_ex == None:
            return_queue.put(0)
            print("Starting analyzing from seed 0.")
        else:
            return_queue.put(last_seed_ex[0])
            print(f"Resuming analyzing from seed {last_seed_ex[0]}.")

        return False

def IsFactorioPathValid(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False

    return True

regex_gen_start = re.compile("^\\s*[\\d|\\.]* Generating map preview: seed=(\\d*)")
regex_report = re.compile("^\\s*[\\d|\\.]* ([\\w|-]*): totalEntityCount=(\\d*)")
regex_goodbye = re.compile("^\\s*[\\d|\\.]* Goodbye")
regex_error = re.compile("error", re.RegexFlag.IGNORECASE)
def RunFactorio(factorio_path: Path, first: int, last: int, size: int, offset: Position, mods: Path,
                reports: Tuple[str], callback: Callable[[int, int, np.ndarray, Dict[str, int]], None]):
    assert(first % 2 == 0 and last % 2 == 0)

    data_path = factorio_data / f"{os.getpid()}"
    os.makedirs(data_path, exist_ok=True)
    with open(data_path / "config.ini", "w") as f:
        f.write(f"[path]\nwrite-data={data_path}{os.sep}\nread-data=__PATH__executable__/../../data")

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
    error = False

    while True:
        line = process.stdout.readline().decode()
        if not line:
            break

        if regex_error.match(line):
            error = True

        if error:
            print(f"Factorio {os.getpid()}: {line}")

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

    if error:
        raise RuntimeError("Factorio has thrown an error")

def EvalZone(queue: mp.JoinableQueue, seed: int, direction: Direction,
             preview: np.ndarray, counts, criteria, is_front_side: bool):
    if counts["iron-ore"] < criteria["min_iron"] or\
        counts["copper-ore"] < criteria["min_copper"] or\
        counts["coal"] < criteria["min_coal"] or\
        counts["stone"] < criteria["min_stone"]:
        return None

    H, W = preview.shape

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

    x = min_i % W
    y = min_i // H

    if is_front_side:
        coal_dt += water_mask.astype(np.uint8) * np.uint8(255)
        coal_lake_distance = np.min(coal_dt)

        iron_center_distance = 0
    else:
        coal_lake_distance = 0

        y_, x_ = FirstZeroPosition(iron_mask, OppositeDirection(direction))
        if direction == Direction.EAST:
            iron_center_distance = x_ + backside_offset - backside_radius
        elif direction == Direction.SOUTH:
            iron_center_distance = y_ + backside_offset - backside_radius
        elif direction == Direction.WEST:
            iron_center_distance = - x_ + backside_offset + backside_radius
        else:
            iron_center_distance = - y_ + backside_offset + backside_radius

    queue.put(Execute(f"""
        INSERT INTO zones (seed, direction, iron_area, copper_area, coal_area, stone_area,
                           iron_copper_d, iron_coal_d, iron_stone_d, lake_coal_d, iron_center_d)
        VALUES ({seed}, {direction}, {counts["iron-ore"]}, {counts["copper-ore"]}, {counts["coal"]}, {counts["stone"]},
                {copper_dt[y, x]}, {coal_dt[y, x]}, {stone_dt[y, x]}, {coal_lake_distance}, {iron_center_distance})
        """)
    )

## maps should be sorted from lowest seed to highest
def EvalBackside(factorio_path: Path, queue: mp.JoinableQueue, first: int, batch_size: int,
                 direction: Direction, criteria):
    
    assert(first % 2 == 0 and batch_size % 2 == 0)
    offset = Position(backside_offset, 0).rotate(direction)

    def Helper(i: int, seed: int, preview: np.ndarray, counts: Dict[str, int]):
        EvalZone(queue, seed, direction, preview, counts, criteria, False)

    RunFactorio(factorio_path, first, first + batch_size - 2, backside_radius * 2,
                offset, mod_path, ("iron-ore", "copper-ore", "coal", "stone"), Helper)

def EvalSeeds(factorio_path: Path, queue: mp.JoinableQueue, exit: Synchronized,
              last_seed: Synchronized, batch_size: int, criteria):
    
    with open(mod_path / "mod-list.json", "w") as f:
        f.write("""
{
    "mods": [
        {
            "name": "base",
            "enabled": true
        },
        {
            "name": "elevated-rails",
            "enabled": false
        },
        {
            "name": "quality",
            "enabled": false
        },
        {
            "name": "space-age",
            "enabled": false
        },
        {
            "name": "common",
            "enabled": true
        },
        {
            "name": "regular-patches",
            "enabled": true
        }
    ]
}
""")
    
    while exit.value == False:
        with last_seed.get_lock():
            seed = last_seed.value
            last_seed.value += batch_size

        if seed >= max_seed:
            break

        if seed + batch_size > max_seed:
            batch_size = max_seed - seed

        EvalBackside(factorio_path, queue, seed, batch_size, Direction.EAST, criteria)
        EvalBackside(factorio_path, queue, seed, batch_size, Direction.SOUTH, criteria)
        EvalBackside(factorio_path, queue, seed, batch_size, Direction.WEST, criteria)
        EvalBackside(factorio_path, queue, seed, batch_size, Direction.NORTH, criteria)

def DatabaseHandler(path: Path, queue: mp.JoinableQueue, return_queue: mp.Queue):
    db = sqlite3.connect(path)
    while True:
        command = queue.get()
        queue.task_done()
        if isinstance(command, Stop):
            break
        else:
            command.execute(db, return_queue)

def main():
    # atexit.register(lambda: shutil.rmtree(factorio_data))

    parser = argparse.ArgumentParser(
        prog="Factorio Seed Finder"
    )

    parser.add_argument("--factorio-path", required=True, type=str)
    parser.add_argument("--criteria", required=True, type=str)
    parser.add_argument("--out", required=True, type=str)
    parser.add_argument("--batch-size", default=25000, type=int)
    parser.add_argument("--factorio-instance-count", default=1, type=int)

    args = parser.parse_args()

    factorio_path = Path(args.factorio_path).absolute()
    if not IsFactorioPathValid(factorio_path):
        print("The provided path for Factorio is not valid.")
        return
    
    if args.batch_size % 2 != 0:
        print("--batch-size must be a multiple of 2.")
    
    with open(args.criteria) as f:
        criteria = json.load(f)

    return_queue = mp.Queue()
    queue = mp.JoinableQueue()
    mp.Process(target=DatabaseHandler, args=(Path(args.out), queue, return_queue), daemon=True).start()

    queue.put(Execute("""
        CREATE TABLE IF NOT EXISTS zones (
            seed BIGINT,
            direction SMALLINT,

            iron_area SMALLINT,
            copper_area SMALLINT,
            coal_area SMALLINT,
            stone_area SMALLINT,

            iron_copper_d SMALLINT,
            iron_coal_d SMALLINT,
            iron_stone_d SMALLINT,

            lake_coal_d SMALLINT,
                    
            iron_center_d SMALLINT
        )
        """)
    )

    queue.put(Execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_seed INTEGER
        )
        """)
    )

    queue.put((LastSeedHelper()))
    last_seed = mp.Value("i", return_queue.get())
    starting_seed = last_seed.value
    starting_time = time.time()

    exit = mp.Value("b", False)
    processes = [mp.Process(target=EvalSeeds, args=(factorio_path, queue, exit, last_seed, args.batch_size, criteria))
                 for _ in range(args.factorio_instance_count)]

    for p in processes:
        p.start()

    next_progress_print = time.time() + 60*30
    next_auto_save = time.time() + 60*10
    while exit.value == False:
        try:
            s = inputimeout(prompt="Type 'exit' to save the current progress and exit. Type stats to get statistics. ",
                            timeout=min(next_progress_print, next_auto_save) - time.time())
        except TimeoutOccurred:
            s = None

        current_time = time.time()

        if next_progress_print <= current_time or (s != None and s.strip() == "stats"):
            print(f"Uptime: {current_time - starting_time:.2f}s")
            print(f"Current progress: seed {last_seed.value:_}/4_294_967_296 ({100 * last_seed.value / max_seed:.3f}%).")
            print(f"{((last_seed.value - starting_seed) / (current_time - starting_time)):.3f} seeds per second on average.")
            next_progress_print = current_time + 60*30

        if next_auto_save <= current_time:
            print(f"Auto saving progress.")
            queue.put(Execute(f"""
                INSERT INTO progress (id, last_seed)
                VALUES (1, {last_seed.value - (args.batch_size * args.factorio_instance_count)})
                ON CONFLICT(id) DO UPDATE SET last_seed=excluded.last_seed
                """)
            )
            queue.put(Commit())
            next_auto_save = current_time + 60*10

        if s != None:
            if s.strip() == "exit":
                exit.value = True

    print("Waiting for batches to finish generate, this may take a few minutes...")
    for p in processes:
        p.join()

    nb_seeds = last_seed.value - starting_seed
    uptime = time.time() - starting_time
    print(f"Generated {nb_seeds} seeds in {uptime:.3f}s. ({nb_seeds / uptime:.3f})/s")
    print("Saving results...")
    queue.put(Execute(f"""
        INSERT INTO progress (id, last_seed)
        VALUES (1, {last_seed.value})
        ON CONFLICT(id) DO UPDATE SET last_seed=excluded.last_seed
        """)
    )
    queue.put(Commit())
    queue.put(Stop())
    queue.join()

    print("Goodbye :)")

if __name__ == "__main__":
    main()