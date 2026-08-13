"""Клетки, чертёж существа и само существо с физикой."""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from evolution import config, hexgrid
from evolution.hexgrid import Coord

SKIN = "skin"
THRUSTER = "thruster"

ROOT: Coord = (0, 0)
"""Центральная клетка — «сердце». Её потеря означает смерть существа."""

SAVE_PATH = Path.home() / ".local" / "share" / "evolution" / "creature.json"
"""Куда сохраняется собранное игроком существо."""


@dataclass
class CellSpec:
    """Описание одной клетки в чертеже."""

    coord: Coord
    kind: str = SKIN
    direction: int = 0  # для двигателя: куда он толкает (0..5)
    group: int = 1  # для двигателя: какой цифрой включается (1..9)


class Blueprint:
    """Чертёж существа: какие клетки где стоят."""

    def __init__(self, cells: dict[Coord, CellSpec] | None = None) -> None:
        self.cells: dict[Coord, CellSpec] = cells if cells is not None else {}
        if ROOT not in self.cells:
            self.cells[ROOT] = CellSpec(ROOT, SKIN)

    def __len__(self) -> int:
        return len(self.cells)

    def can_place(self, coord: Coord) -> bool:
        """Ставить можно только вплотную к уже поставленным клеткам."""
        if coord in self.cells:
            return False
        return any(n in self.cells for n in hexgrid.neighbors(coord))

    def place(self, spec: CellSpec) -> bool:
        if not self.can_place(spec.coord):
            return False
        self.cells[spec.coord] = spec
        return True

    def remove(self, coord: Coord) -> bool:
        """Убирает клетку; вместе с ней уходит всё, что через неё держалось."""
        if coord == ROOT or coord not in self.cells:
            return False
        del self.cells[coord]
        for orphan in set(self.cells) - connected_from(set(self.cells), ROOT):
            del self.cells[orphan]
        return True

    def copy(self) -> Blueprint:
        return Blueprint({c: CellSpec(s.coord, s.kind, s.direction, s.group) for c, s in self.cells.items()})

    # --- сохранение и загрузка ---

    def to_json(self) -> str:
        return json.dumps(
            [
                {"q": s.coord[0], "r": s.coord[1], "kind": s.kind, "dir": s.direction, "group": s.group}
                for s in self.cells.values()
            ]
        )

    @classmethod
    def from_json(cls, text: str) -> Blueprint:
        cells: dict[Coord, CellSpec] = {}
        for item in json.loads(text):
            coord = (int(item["q"]), int(item["r"]))
            cells[coord] = CellSpec(coord, item["kind"], int(item["dir"]), int(item["group"]))
        return cls(cells)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Blueprint | None:
        try:
            return cls.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return None


def connected_from(coords: set[Coord], start: Coord) -> set[Coord]:
    """Все клетки набора, до которых можно дойти от `start` по соседям."""
    if start not in coords:
        return set()
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for n in hexgrid.neighbors(current):
            if n in coords and n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


def cell_color(coord: Coord, spec: CellSpec, is_player: bool = True) -> tuple[int, int, int]:
    """Цвет клетки: ядро, двигатель или кожа — своя палитра у игрока и у врага."""
    if coord == ROOT:
        return config.CORE_COLOR
    if spec.kind == THRUSTER:
        return config.THRUSTER_COLOR if is_player else config.ENEMY_THRUSTER_COLOR
    return config.SKIN_COLOR if is_player else config.ENEMY_SKIN_COLOR


def default_blueprint() -> Blueprint:
    """Простое существо на случай, если игрок ещё ничего не собирал."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), SKIN))
    bp.place(CellSpec((1, -1), SKIN))
    bp.place(CellSpec((-1, 0), THRUSTER, direction=0, group=1))
    bp.place(CellSpec((-1, 1), THRUSTER, direction=5, group=2))
    bp.place(CellSpec((0, -1), THRUSTER, direction=2, group=3))
    return bp


# --------------------------------------------------------------------------
# вспомогательная математика векторов (без pygame, чтобы это можно было
# проверять тестами без окна)
# --------------------------------------------------------------------------


def rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


@dataclass
class Creature:
    """Существо: чертёж + живые клетки + физика жёсткого тела."""

    blueprint: Blueprint
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    spin: float = 0.0
    is_player: bool = False

    alive_cells: set[Coord] = field(default_factory=set)
    com_x: float = 0.0
    com_y: float = 0.0
    mass: float = 0.0
    inertia: float = 1.0
    radius: float = 0.0
    damage_timer: float = 0.0

    def __post_init__(self) -> None:
        self.alive_cells = set(self.blueprint.cells)
        self._recompute(keep_position=False)

    # --- геометрия ---

    def local_pos(self, coord: Coord) -> tuple[float, float]:
        """Положение клетки внутри существа, считая от центра тяжести."""
        px, py = hexgrid.hex_to_pixel(coord, config.HEX_SIZE)
        return px - self.com_x, py - self.com_y

    def cell_world_pos(self, coord: Coord) -> tuple[float, float]:
        lx, ly = self.local_pos(coord)
        rx, ry = rotate(lx, ly, self.angle)
        return self.x + rx, self.y + ry

    def cell_offset(self, coord: Coord) -> tuple[float, float]:
        """Вектор от центра тяжести до клетки в мировых осях."""
        lx, ly = self.local_pos(coord)
        return rotate(lx, ly, self.angle)

    def point_velocity(self, ox: float, oy: float) -> tuple[float, float]:
        """Скорость точки тела со смещением (ox, oy) от центра тяжести."""
        return self.vx - self.spin * oy, self.vy + self.spin * ox

    def _recompute(self, keep_position: bool = True) -> None:
        """Пересчитывает массу, центр тяжести и момент инерции."""
        if not self.alive_cells:
            self.mass = config.CELL_MASS
            self.inertia = 1.0
            self.radius = config.HEX_SIZE
            return

        points = [hexgrid.hex_to_pixel(c, config.HEX_SIZE) for c in self.alive_cells]
        new_com_x = sum(p[0] for p in points) / len(points)
        new_com_y = sum(p[1] for p in points) / len(points)

        if keep_position:
            # Центр тяжести уехал — сдвигаем тело так, чтобы клетки визуально
            # остались на своих местах.
            dx, dy = rotate(new_com_x - self.com_x, new_com_y - self.com_y, self.angle)
            self.x += dx
            self.y += dy

        self.com_x, self.com_y = new_com_x, new_com_y
        self.mass = config.CELL_MASS * len(self.alive_cells)

        inertia = 0.0
        radius = 0.0
        cell_inertia = config.CELL_MASS * config.HEX_SIZE**2 * 0.5
        for px, py in points:
            dx, dy = px - new_com_x, py - new_com_y
            inertia += config.CELL_MASS * (dx * dx + dy * dy) + cell_inertia
            radius = max(radius, math.hypot(dx, dy))
        self.inertia = max(inertia, 1.0)
        self.radius = radius + config.CELL_RADIUS

    # --- состояние ---

    @property
    def is_dead(self) -> bool:
        return ROOT not in self.alive_cells or not self.alive_cells

    @property
    def lost_count(self) -> int:
        return len(self.blueprint.cells) - len(self.alive_cells)

    def thrusters(self) -> list[CellSpec]:
        return [
            spec
            for coord, spec in self.blueprint.cells.items()
            if spec.kind == THRUSTER and coord in self.alive_cells
        ]

    def groups(self) -> set[int]:
        return {spec.group for spec in self.thrusters()}

    # --- урон и лечение ---

    def remove_cell(self, coord: Coord) -> list[Coord]:
        """Выбивает клетку. Всё, что держалось через неё, тоже отваливается.

        Возвращает список отвалившихся клеток — из них получится еда.
        """
        if coord not in self.alive_cells:
            return []
        self.alive_cells.discard(coord)
        lost = [coord]
        if coord != ROOT:
            still_attached = connected_from(self.alive_cells, ROOT)
            orphans = self.alive_cells - still_attached
            self.alive_cells = still_attached
            lost.extend(orphans)
        else:
            # Потеряли сердце — разваливается всё остальное.
            lost.extend(self.alive_cells)
            self.alive_cells = set()
        self._recompute()
        return lost

    def heal(self, count: int = 1) -> int:
        """Возвращает утраченные клетки. Расти сверх чертежа нельзя."""
        healed = 0
        for _ in range(count):
            candidates = [
                c
                for c in self.blueprint.cells
                if c not in self.alive_cells
                and (not self.alive_cells or any(n in self.alive_cells for n in hexgrid.neighbors(c)))
            ]
            if not candidates:
                break
            candidates.sort(key=lambda c: hexgrid.distance(ROOT, c))
            self.alive_cells.add(candidates[0])
            healed += 1
        if healed:
            self._recompute()
        return healed

    # --- физика ---

    def apply_thrust(self, active_groups: set[int], dt: float) -> None:
        fx = fy = torque = 0.0
        for spec in self.thrusters():
            if spec.group not in active_groups:
                continue
            dx, dy = hexgrid.direction_vector(spec.direction)
            wx, wy = rotate(dx, dy, self.angle)
            wx *= config.THRUST_FORCE
            wy *= config.THRUST_FORCE
            ox, oy = self.cell_offset(spec.coord)
            fx += wx
            fy += wy
            torque += ox * wy - oy * wx
        self.vx += fx / self.mass * dt
        self.vy += fy / self.mass * dt
        self.spin += torque / self.inertia * dt

    def step(self, dt: float) -> None:
        # вода тормозит
        damping = math.exp(-config.LINEAR_DRAG * dt)
        self.vx *= damping
        self.vy *= damping
        self.spin *= math.exp(-config.ANGULAR_DRAG * dt)

        speed = math.hypot(self.vx, self.vy)
        if speed > config.MAX_SPEED:
            k = config.MAX_SPEED / speed
            self.vx *= k
            self.vy *= k

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        self.damage_timer = max(0.0, self.damage_timer - dt)
        self._keep_in_world()

    def _keep_in_world(self) -> None:
        r = self.radius
        if self.x < r:
            self.x, self.vx = r, abs(self.vx) * 0.5
        elif self.x > config.WORLD_WIDTH - r:
            self.x, self.vx = config.WORLD_WIDTH - r, -abs(self.vx) * 0.5
        if self.y < r:
            self.y, self.vy = r, abs(self.vy) * 0.5
        elif self.y > config.WORLD_HEIGHT - r:
            self.y, self.vy = config.WORLD_HEIGHT - r, -abs(self.vy) * 0.5
