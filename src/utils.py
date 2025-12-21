from __future__ import annotations
from enum import IntEnum
from typing import *
import math
import time
from functools import wraps

class Timer:
    _totals = {}
    _calls = {}

    def _SetName(self, name: str):
        self._name = name
        if name not in self._totals:
            self._totals[name] = 0
            self._calls[name] = 0

    def __init__(self, name: str):
        self._SetName(name)
        self._init_time = time.time()

    def Reset(self, new_name: str = None):
        if new_name != None:
            self._SetName(new_name)

        self._init_time = time.time()

    def Print(self):
        now = time.time()
        duration = now - self._init_time
        self._init_time = now
        self._totals[self._name] += duration*1000
        self._calls[self._name] += 1

        print(f"{self._name}: {(duration*1000):.3f}ms elapsed; Average: {self._totals[self._name] / self._calls[self._name]:.3f}ms")

def timer(name):
    def timer(func):
        @wraps(func)
        def Inner(*args, **kwargs):
            t = Timer(name)
            retval = func(*args, **kwargs)
            t.Print()
            return retval
        return Inner
    return timer

class Tile(IntEnum):
    IRON = 0
    COPPER = 1
    COAL = 2
    STONE = 3
    WATER = 4
    NORMAL = 5

class Direction(IntEnum):
    EAST = 0
    SOUTH = 1
    WEST = 2
    NORTH = 3

class Position:
    x: int
    y: int

    def __init__(self, x: int = 0, y: int = 0):
        self.x = x
        self.y = y
    
    def __repr__(self) -> str:
        return f"Position(x={self.x}, y={self.y})"

    def __iter__(self):
        yield self.x
        yield self.y

    def to_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)

    @classmethod
    def from_tuple(cls, t: Tuple[int, int]) -> Position:
        return cls(int(t[0]), int(t[1]))

    def copy(self) -> Position:
        return Position(self.x, self.y)

    def _as_position(self, other: Union[Position, Tuple[int, int], Sequence[int]]) -> Position:
        if isinstance(other, Position):
            return other
        if isinstance(other, (tuple, list)):
            if len(other) != 2:
                raise ValueError("Expected sequence of length 2")
            return Position(int(other[0]), int(other[1]))
        raise TypeError("Operand must be Position or 2-length sequence")

    def __add__(self, other: Union[Position, Tuple[int, int], Sequence[int]]):
        o = self._as_position(other)
        return Position(self.x + o.x, self.y + o.y)

    def __sub__(self, other: Union[Position, Tuple[int, int], Sequence[int]]):
        o = self._as_position(other)
        return Position(self.x - o.x, self.y - o.y)

    def __neg__(self) -> Position:
        return Position(-self.x, -self.y)

    def __mul__(self, scalar: Union[int, float]):
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return Position(int(self.x * scalar), int(self.y * scalar))

    __rmul__ = __mul__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return False
        return self.x == other.x and self.y == other.y

    def distance_squared_to(self, other: Union[Position, Tuple[int, int], Sequence[int]]) -> int:
        o = self._as_position(other)
        dx = self.x - o.x
        dy = self.y - o.y
        return dx * dx + dy * dy

    def distance_to(self, other: Union[Position, Tuple[int, int], Sequence[int]]) -> float:
        o = self._as_position(other)
        return math.hypot(self.x - o.x, self.y - o.y)
    
    def rotate(self, direction: Direction) -> Position:
        if direction == Direction.EAST:
            return self.copy()
        if direction == Direction.SOUTH:
            return Position(-self.y, self.x)
        if direction == Direction.WEST:
            return Position(-self.x, -self.y)
        if direction == Direction.NORTH:
            return Position(self.y, -self.x)
        raise ValueError("Invalid Direction for rotation")
    
    @staticmethod
    def Min(p1: Position, p2: Position) -> Position:
        return Position(min(p1.x, p2.x), min(p1.y, p2.y))
    
    @staticmethod
    def Max(p1: Position, p2: Position) -> Position:
        return Position(max(p1.x, p2.x), max(p1.y, p2.y))

class Area:
    left_top: Position
    right_bottom: Position

    def __init__(self, left_top: Position, right_bottom: Position):
        self.left_top = left_top
        self.right_bottom = right_bottom

    @staticmethod
    def FromCenterAndRadius(center: Position, radius: int):
        vec = Position(radius, radius)
        return Area(center - vec, center + vec)

    def Center(self) -> Position:
        return (self.left_top + self.right_bottom) / 2

    def Collides(self, arg: Union[Position, Area]) -> bool:
        if type(arg) == Position:
            return max(self.left_top.x - arg.x, 0, arg.x - self.right_bottom.x) == 0 and\
                   max(self.left_top.y - arg.y, 0, arg.y - self.right_bottom.y) == 0
        elif type(arg) == Area:
            return self.left_top.x <= arg.right_bottom.x and\
                   self.right_bottom.x >= arg.left_top.x and\
                   self.left_top.y <= arg.right_bottom.y and\
                   self.right_bottom.y >= arg.left_top.y
        else:
            raise TypeError("Area.Collides first argument must be Position or Area")