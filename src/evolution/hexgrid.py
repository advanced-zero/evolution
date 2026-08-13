"""Математика шестиугольной сетки.

Используем «остроконечные» гексы и осевые координаты (q, r): сосед номер 0
лежит ровно по оси +x, то есть прямо по курсу существа. Номер соседа (0..5)
служит и направлением двигателя.
"""

from __future__ import annotations

import math

SQRT3 = math.sqrt(3.0)

# Соседи в осевых координатах: 0 — вправо (0°), дальше по 60° по часовой стрелке.
DIRECTIONS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (0, -1),
    (1, -1),
)

Coord = tuple[int, int]


def hex_to_pixel(coord: Coord, size: float) -> tuple[float, float]:
    """Центр клетки в пикселях относительно клетки (0, 0)."""
    q, r = coord
    return (size * SQRT3 * (q + r / 2.0), size * 1.5 * r)


def pixel_to_hex(x: float, y: float, size: float) -> Coord:
    """Какой клетке принадлежит точка."""
    q = (SQRT3 / 3.0 * x - y / 3.0) / size
    r = (2.0 / 3.0) * y / size
    return _round(q, r)


def _round(q: float, r: float) -> Coord:
    """Округление дробных осевых координат до ближайшей клетки."""
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return int(rq), int(rr)


def neighbors(coord: Coord) -> list[Coord]:
    q, r = coord
    return [(q + dq, r + dr) for dq, dr in DIRECTIONS]


def neighbor(coord: Coord, direction: int) -> Coord:
    dq, dr = DIRECTIONS[direction % 6]
    return coord[0] + dq, coord[1] + dr


def distance(a: Coord, b: Coord) -> int:
    """Расстояние в клетках."""
    aq, ar = a
    bq, br = b
    return (abs(aq - bq) + abs(aq + ar - bq - br) + abs(ar - br)) // 2


def spiral(radius: int) -> list[Coord]:
    """Все клетки в радиусе `radius` от центра, от центра наружу."""
    out: list[Coord] = []
    for q in range(-radius, radius + 1):
        for r in range(-radius, radius + 1):
            if distance((0, 0), (q, r)) <= radius:
                out.append((q, r))
    def angle(c: Coord) -> float:
        x, y = hex_to_pixel(c, 1.0)
        return math.atan2(y, x)

    out.sort(key=lambda c: (distance((0, 0), c), angle(c)))
    return out


def corners(cx: float, cy: float, size: float, angle: float = 0.0) -> list[tuple[float, float]]:
    """Шесть углов шестиугольника с центром (cx, cy), повёрнутого на `angle` радиан."""
    pts = []
    for i in range(6):
        a = angle + math.pi / 6.0 + math.pi / 3.0 * i
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return pts


def direction_vector(direction: int) -> tuple[float, float]:
    """Единичный вектор в сторону соседа `direction`."""
    x, y = hex_to_pixel(DIRECTIONS[direction % 6], 1.0)
    length = math.hypot(x, y)
    return x / length, y / length
