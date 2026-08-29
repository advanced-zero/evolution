"""Клетки, чертёж существа и само существо с физикой."""

from __future__ import annotations

import json
import math
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from evolution import config, hexgrid
from evolution.hexgrid import Coord

SKIN = "skin"
BONE = "bone"
THRUSTER = "thruster"
PROCESSOR = "processor"
EYE = "eye"
PHOTOSYNTH = "photosynth"

KINDS = (SKIN, BONE, THRUSTER, PROCESSOR, EYE, PHOTOSYNTH)
"""Виды клеток в том порядке, в котором их перебирает редактор."""

LOOK_FOOD = "food"
LOOK_ENEMY = "enemy"
LOOK_NORTH = "north"
LOOK_EAST = "east"
LOOK_SOUTH = "south"
LOOK_WEST = "west"
EYE_LOOKS = (LOOK_FOOD, LOOK_ENEMY, LOOK_NORTH, LOOK_EAST, LOOK_SOUTH, LOOK_WEST)
"""Куда может смотреть зрительная клетка: крутится колёсиком в редакторе."""

EYE_LOOK_NAMES = {
    LOOK_FOOD: "еда",
    LOOK_ENEMY: "враг",
    LOOK_NORTH: "север",
    LOOK_EAST: "восток",
    LOOK_SOUTH: "юг",
    LOOK_WEST: "запад",
}

# Стороны света — оси мира, не нос существа: +x восток, +y юг.
EYE_LOOK_VECTORS: dict[str, tuple[float, float]] = {
    LOOK_NORTH: (0.0, -1.0),
    LOOK_EAST: (1.0, 0.0),
    LOOK_SOUTH: (0.0, 1.0),
    LOOK_WEST: (-1.0, 0.0),
}

ROOT: Coord = (0, 0)
"""Центральная клетка — «мозг». Её потеря означает смерть существа.

Мозг же держит форму тела: остальные клетки гнутся относительно него. И он же
самый прожорливый — за каждый удар голода просит больше обычной клетки.
"""

SAVE_PATH = Path.home() / ".local" / "share" / "evolution" / "creature.json"
"""Куда сохраняется собранное игроком существо."""


@dataclass
class CellSpec:
    """Описание одной клетки в чертеже."""

    coord: Coord
    kind: str = SKIN
    direction: int = 0  # для двигателя: куда он толкает (0..5)
    group: int = 1  # для двигателя: какой цифрой включается (1..9)
    look: str = LOOK_FOOD  # для глаза: еда, враг или сторона света


# --------------------------------------------------------------------------
# свойства видов клеток — чтобы «если кость» не расползалось по всему коду
# --------------------------------------------------------------------------


def cell_mass(kind: str) -> float:
    """Кость тяжелее кожи и двигателя."""
    return config.BONE_MASS if kind == BONE else config.CELL_MASS


def cell_cost(kind: str) -> int:
    """Во сколько очков постройки обходится клетка."""
    return config.CELL_COST.get(kind, 1)


def cell_upkeep(kind: str, is_brain: bool = False) -> float:
    """Сколько энергии клетка просит за один удар голода, пока без дела.

    Кость не ест вовсе — тем и хороша: скелет ничего не стоит в содержании.
    Простаивающий переработчик тоже бесплатен, платить придётся за работу.
    """
    if is_brain:
        return config.BRAIN_UPKEEP
    return config.CELL_UPKEEP.get(kind, 1.0)


def cell_work_upkeep(kind: str) -> float:
    """Сколько просит клетка, проработавшая весь удар голода целиком.

    Работают только двигатель (жжёт топливо) и переработчик (топит обломки);
    остальным работать нечем, для них это просто их обычный аппетит.
    """
    if kind == THRUSTER:
        return config.THRUSTER_WORK_UPKEEP
    if kind == PROCESSOR:
        return config.PROCESSOR_WORK_UPKEEP
    return cell_upkeep(kind)


def food_energy(kind: str, is_brain: bool = False) -> float:
    """Сколько энергии даёт обломок этой клетки: что дороже строить, то сытнее."""
    if is_brain:
        return config.BRAIN_FOOD_ENERGY
    return config.FOOD_ENERGY.get(kind, 5.0)


def cell_anchor(kind: str) -> float:
    """Насколько цепко клетка держится за своё место в чертеже."""
    return config.SOFT_ANCHOR_BONE if kind == BONE else config.SOFT_ANCHOR_SKIN


def link_stiffness(hard_a: bool, hard_b: bool) -> float:
    """Жёсткость связи двух клеток: мягкое звено делает мягкой всю связь."""
    return config.SOFT_LINK_BONE if hard_a and hard_b else config.SOFT_LINK_SKIN


def link_transmit(hard_a: bool, hard_b: bool) -> float:
    """Какая доля толчка проходит через связь двух клеток."""
    return config.SOFT_TRANSMIT_BONE if hard_a and hard_b else config.SOFT_TRANSMIT_SKIN


@dataclass
class Muscle:
    """Верёвка между двумя клетками: пока держат её цифру, тянет концы вместе.

    Это не клетка: мышца ничего не весит, ест энергию только за отработанное
    время и стоит по очку за каждую клетку своей длины.
    """

    a: Coord
    b: Coord
    group: int = 1
    strength: int = 1  # 1..MUSCLE_MAX_STRENGTH, крутится колёсиком в редакторе

    def length(self) -> int:
        """Длина в клетках — она же цена в очках."""
        return hexgrid.distance(self.a, self.b)

    def cost(self) -> int:
        return self.length()

    def work_upkeep(self) -> float:
        """Сколько просит мышца, проработавшая весь удар голода."""
        return config.MUSCLE_WORK_UPKEEP * self.strength


class Blueprint:
    """Чертёж существа: какие клетки где стоят и какие мышцы между ними."""

    def __init__(
        self, cells: dict[Coord, CellSpec] | None = None, muscles: list[Muscle] | None = None
    ) -> None:
        self.cells: dict[Coord, CellSpec] = cells if cells is not None else {}
        self.muscles: list[Muscle] = muscles if muscles is not None else []
        if ROOT not in self.cells:
            self.cells[ROOT] = CellSpec(ROOT, SKIN)

    def __len__(self) -> int:
        return len(self.cells)

    def cost(self) -> int:
        """Во сколько очков обходится вся постройка: клетки плюс длина мышц."""
        cells = sum(cell_cost(spec.kind) for spec in self.cells.values())
        return cells + sum(m.cost() for m in self.muscles)

    def appetite(self) -> float:
        """Сколько чертёж просит за удар голода в покое — от этого считается бак."""
        return sum(cell_upkeep(spec.kind, coord == ROOT) for coord, spec in self.cells.items())

    def tank(self) -> float:
        """Размер бака полного тела по этому чертежу."""
        return self.appetite() * config.ENERGY_RESERVE

    def add_muscle(self, muscle: Muscle) -> bool:
        """Натягивает верёвку между двумя разными живыми клетками чертежа."""
        if muscle.a == muscle.b:
            return False
        if muscle.a not in self.cells or muscle.b not in self.cells:
            return False
        if self.find_muscle(muscle.a, muscle.b) is not None:
            return False
        self.muscles.append(muscle)
        return True

    def find_muscle(self, a: Coord, b: Coord) -> Muscle | None:
        for m in self.muscles:
            if {m.a, m.b} == {a, b}:
                return m
        return None

    def muscles_at(self, coord: Coord) -> list[Muscle]:
        return [m for m in self.muscles if coord in (m.a, m.b)]

    def _drop_dangling_muscles(self) -> None:
        """Мышца без обоих концов в чертеже не имеет смысла."""
        self.muscles = [m for m in self.muscles if m.a in self.cells and m.b in self.cells]

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
        self._drop_dangling_muscles()
        return True

    def remove_muscle(self, a: Coord, b: Coord) -> bool:
        muscle = self.find_muscle(a, b)
        if muscle is None:
            return False
        self.muscles.remove(muscle)
        return True

    def copy(self) -> Blueprint:
        return Blueprint(
            {c: CellSpec(s.coord, s.kind, s.direction, s.group, s.look) for c, s in self.cells.items()},
            [Muscle(m.a, m.b, m.group, m.strength) for m in self.muscles],
        )

    # --- сохранение и загрузка ---

    def to_dict(self) -> dict:
        return {
            "cells": [
                {
                    "q": s.coord[0],
                    "r": s.coord[1],
                    "kind": s.kind,
                    "dir": s.direction,
                    "group": s.group,
                    "look": s.look,
                }
                for s in self.cells.values()
            ],
            "muscles": [
                {
                    "aq": m.a[0], "ar": m.a[1], "bq": m.b[0], "br": m.b[1],
                    "group": m.group, "strength": m.strength,
                }
                for m in self.muscles
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict | list) -> Blueprint:
        # сохранение от версии без мышц — просто список клеток
        raw_cells = data if isinstance(data, list) else data["cells"]
        raw_muscles = [] if isinstance(data, list) else data.get("muscles", [])

        cells: dict[Coord, CellSpec] = {}
        for item in raw_cells:
            coord = (int(item["q"]), int(item["r"]))
            # незнакомый вид (сохранение от старой версии) считаем кожей
            kind = item["kind"] if item["kind"] in KINDS else SKIN
            look = item.get("look", LOOK_FOOD)
            if look not in EYE_LOOKS:
                look = LOOK_FOOD
            cells[coord] = CellSpec(coord, kind, int(item["dir"]), int(item["group"]), look)

        blueprint = cls(cells)
        for item in raw_muscles:
            blueprint.add_muscle(
                Muscle(
                    (int(item["aq"]), int(item["ar"])),
                    (int(item["bq"]), int(item["br"])),
                    int(item["group"]),
                    int(item["strength"]),
                )
            )
        return blueprint

    @classmethod
    def from_json(cls, text: str) -> Blueprint:
        return cls.from_dict(json.loads(text))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Blueprint | None:
        try:
            return cls.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return None


class Species:
    """Цепочка этапов одного существа: в бою оно начинает с первого и линяет дальше."""

    def __init__(self, stages: list[Blueprint] | None = None) -> None:
        self.stages: list[Blueprint] = [s.copy() for s in stages] if stages else [Blueprint()]
        if not self.stages:
            self.stages = [Blueprint()]

    def __len__(self) -> int:
        return len(self.stages)

    def copy(self) -> Species:
        return Species(self.stages)

    def budget(self, index: int) -> float:
        """Потолок очков этапа: у первого 50, у следующего — бак предыдущего."""
        if index <= 0:
            return float(config.CELL_BUDGET)
        return self.stages[index - 1].tank()

    def valid(self) -> bool:
        return all(stage.cost() <= self.budget(i) + 1e-6 for i, stage in enumerate(self.stages))

    def to_json(self) -> str:
        return json.dumps({"stages": [stage.to_dict() for stage in self.stages]})

    @classmethod
    def from_json(cls, text: str) -> Species:
        data = json.loads(text)
        if isinstance(data, dict) and "stages" in data:
            stages = [Blueprint.from_dict(item) for item in data["stages"]]
            return cls(stages or [Blueprint()])
        return cls([Blueprint.from_dict(data)])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Species | None:
        try:
            return cls.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return None


def evolve_cost(previous: Blueprint, nxt: Blueprint) -> int:
    """Сколько энергии нужно, чтобы начать рост: новые клетки и новые мышцы."""
    cells = sum(cell_cost(spec.kind) for coord, spec in nxt.cells.items() if coord not in previous.cells)
    old_muscles = {frozenset((m.a, m.b)) for m in previous.muscles}
    muscles = sum(m.cost() for m in nxt.muscles if frozenset((m.a, m.b)) not in old_muscles)
    return cells + muscles


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
    """Цвет клетки: ядро, двигатель, кость или кожа — своя палитра у врага."""
    if coord == ROOT:
        return config.CORE_COLOR
    if spec.kind == THRUSTER:
        return config.THRUSTER_COLOR if is_player else config.ENEMY_THRUSTER_COLOR
    if spec.kind == PROCESSOR:
        return config.PROCESSOR_COLOR if is_player else config.ENEMY_PROCESSOR_COLOR
    if spec.kind == EYE:
        return config.EYE_COLOR if is_player else config.ENEMY_EYE_COLOR
    if spec.kind == PHOTOSYNTH:
        return config.PHOTOSYNTH_COLOR if is_player else config.ENEMY_PHOTOSYNTH_COLOR
    if spec.kind == BONE:
        return config.BONE_COLOR if is_player else config.ENEMY_BONE_COLOR
    return config.SKIN_COLOR if is_player else config.ENEMY_SKIN_COLOR


def default_blueprint() -> Blueprint:
    """Простое существо на случай, если игрок ещё ничего не собирал."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), SKIN))
    bp.place(CellSpec((1, -1), PROCESSOR))  # без переработчика есть нечем
    bp.place(CellSpec((-1, 0), THRUSTER, direction=0, group=1))
    bp.place(CellSpec((-1, 1), THRUSTER, direction=5, group=2))
    bp.place(CellSpec((0, -1), THRUSTER, direction=2, group=3))
    return bp


# --------------------------------------------------------------------------
# вспомогательная математика векторов (без pygame, чтобы это можно было
# проверять тестами без окна)
# --------------------------------------------------------------------------


def _angle_between(ax: float, ay: float, bx: float, by: float) -> float:
    """Угол между двумя векторами, 0..pi."""
    dot = ax * bx + ay * by
    cross = ax * by - ay * bx
    return math.atan2(abs(cross), dot)


def rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


@dataclass
class Creature:
    """Существо: чертёж, живые клетки и физика мягкого тела.

    Тело держится на «несущем кадре» — положении, повороте и скоростях всего
    существа. Поверх него каждая живая клетка имеет своё смещение от места в
    чертеже: кожа охотно гнётся, кость почти нет, мозг не смещается вовсе.

    Тело ещё и кормится: раз в HUNGER_PERIOD клетки просят энергию, и на кого
    её не хватило — тот отваливается.
    """

    blueprint: Blueprint
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    spin: float = 0.0
    is_player: bool = False
    rng: random.Random | None = None  # мир даёт свой, чтобы тесты повторялись

    alive_cells: set[Coord] = field(default_factory=set)
    com_x: float = 0.0
    com_y: float = 0.0
    mass: float = 0.0
    inertia: float = 1.0
    radius: float = 0.0
    damage_timer: float = 0.0

    # энергия: сколько накоплено, какой у тела бак и когда следующий удар голода
    energy: float = 0.0
    appetite: float = 0.0
    max_energy: float = 0.0
    hunger_timer: float = 0.0
    since_hunger: float = 0.0  # сколько секунд идёт нынешний интервал голода
    # наработка двигателей и переработчиков за нынешний интервал голода
    work_time: dict[Coord, float] = field(default_factory=dict)
    # аппетит фотосинтезирующих клеток на нынешний интервал: бросок 0/1,
    # свежий на каждый удар голода (см. reset_hunger)
    photo_upkeep: dict[Coord, float] = field(default_factory=dict)
    repair_progress: float = 0.0
    processing: set[Coord] = field(default_factory=set)  # кто прямо сейчас топит обломок

    # мягкое тело: смещение клетки от своего места и скорость этого смещения
    # (в местных осях тела, то есть без учёта поворота)
    offsets: dict[Coord, list[float]] = field(default_factory=dict)
    offset_vels: dict[Coord, list[float]] = field(default_factory=dict)
    transmit: dict[Coord, float] = field(default_factory=dict)
    torn: list[Coord] = field(default_factory=list)
    # насколько клетку смяло и вдоль какой оси: (доля 0..1, угол в местных осях)
    squeeze: dict[Coord, tuple[float, float]] = field(default_factory=dict)
    # кости, стоящие вплотную, живут одним жёстким куском
    bone_pieces: list[list[Coord]] = field(default_factory=list)
    # суставы: тройки «сосед — клетка — сосед» с противоположных сторон
    joints: list[tuple[Coord, Coord, Coord]] = field(default_factory=list)
    pulling: set[int] = field(default_factory=set)  # какие мышцы тянут прямо сейчас
    muscle_work: dict[int, float] = field(default_factory=dict)  # наработка мышц
    # этапы развития: в бою начинает с первого и само зарастает до следующего
    species: Species | None = None
    stage_index: int = 0
    evolving: bool = False
    _molt_from: set[Coord] = field(default_factory=set)  # клетки прошлого этапа — дырки бесплатны

    # перегрев двигателей — только у игрока, отдельно по каждой группе (кнопке)
    thruster_heat: dict[int, float] = field(default_factory=dict)  # 0..1
    thruster_cooldown: dict[int, float] = field(default_factory=dict)  # сек до конца колдауна
    thruster_idle: dict[int, float] = field(default_factory=dict)  # сколько подряд группа не нажата

    def __post_init__(self) -> None:
        if self.species is None:
            self.species = Species([self.blueprint])
        else:
            self.species = self.species.copy()
        self.blueprint = self.species.stages[0].copy()
        self.stage_index = 0
        self.evolving = False
        self.alive_cells = set(self.blueprint.cells)
        self._recompute(keep_position=False)
        # игрок выходит голодноватым, иначе сразу линяет без боя; враги — сытые
        if self.is_player:
            self.energy = self.max_energy * config.PLAYER_START_ENERGY
        else:
            self.energy = self.max_energy
        self.reset_hunger()
        self._prev_vx, self._prev_vy, self._prev_spin = self.vx, self.vy, self.spin
        self._water_dv = (0.0, 0.0, 0.0)

    # --- геометрия ---

    def kind_of(self, coord: Coord) -> str:
        return self.blueprint.cells[coord].kind

    def is_hard(self, coord: Coord) -> bool:
        """Твёрдые клетки — кость и мозг: они держат форму тела.

        Двигатель, прикрученный к твёрдому, тоже держится крепко: скелет от
        мозга к двигателям — это как раз то, ради чего ставят кость.
        """
        if coord == ROOT:
            return True
        kind = self.kind_of(coord)
        if kind == BONE:
            return True
        if kind == THRUSTER:
            return any(
                n in self.alive_cells and (n == ROOT or self.kind_of(n) == BONE)
                for n in hexgrid.neighbors(coord)
            )
        return False

    def rest_pos(self, coord: Coord) -> tuple[float, float]:
        """Место клетки по чертежу — куда её тянет обратно, если тело согнули."""
        px, py = hexgrid.hex_to_pixel(coord, config.HEX_SIZE)
        return px - self.com_x, py - self.com_y

    def local_pos(self, coord: Coord) -> tuple[float, float]:
        """Где клетка сейчас внутри существа: место по чертежу плюс изгиб."""
        px, py = self.rest_pos(coord)
        off = self.offsets.get(coord)
        if off is None:
            return px, py
        return px + off[0], py + off[1]

    def cell_world_pos(self, coord: Coord) -> tuple[float, float]:
        lx, ly = self.local_pos(coord)
        rx, ry = rotate(lx, ly, self.angle)
        return self.x + rx, self.y + ry

    def cell_offset(self, coord: Coord) -> tuple[float, float]:
        """Вектор от центра тяжести до клетки в мировых осях."""
        lx, ly = self.local_pos(coord)
        return rotate(lx, ly, self.angle)

    def visual_extent(self) -> float:
        """Насколько тело сейчас разбросано от центра тяжести — для камеры.

        В отличие от `radius` (запас для физики столкновений на случай
        наихудшего изгиба, включает `SOFT_MAX_OFFSET`), здесь только
        фактическое положение клеток по чертежу плюс их собственный радиус.
        """
        if not self.alive_cells:
            return config.HEX_SIZE
        farthest = 0.0
        for c in self.alive_cells:
            px, py = hexgrid.hex_to_pixel(c, config.HEX_SIZE)
            farthest = max(farthest, math.hypot(px - self.com_x, py - self.com_y))
        return farthest + config.CELL_RADIUS

    def point_velocity(self, ox: float, oy: float) -> tuple[float, float]:
        """Скорость точки тела со смещением (ox, oy) от центра тяжести."""
        return self.vx - self.spin * oy, self.vy + self.spin * ox

    def cell_velocity(self, coord: Coord) -> tuple[float, float]:
        """Скорость клетки: движение тела плюс её собственное шевеление."""
        ox, oy = self.cell_offset(coord)
        vx, vy = self.point_velocity(ox, oy)
        vel = self.offset_vels.get(coord)
        if vel is None:
            return vx, vy
        wx, wy = rotate(vel[0], vel[1], self.angle)
        return vx + wx, vy + wy

    def render_angle(self, coord: Coord) -> float:
        """Угол клетки на экране: изогнутое тело доворачивает свои клетки."""
        if coord == ROOT:
            return self.angle
        parents = [n for n in hexgrid.neighbors(coord) if n in self.alive_cells]
        if not parents:
            return self.angle
        parent = min(parents, key=lambda n: hexgrid.distance(ROOT, n))
        ox, oy = self.offsets.get(coord, (0.0, 0.0))
        px, py = self.offsets.get(parent, (0.0, 0.0))
        rx, ry = hexgrid.hex_to_pixel(coord, config.HEX_SIZE)
        qx, qy = hexgrid.hex_to_pixel(parent, config.HEX_SIZE)
        lx, ly = rx - qx, ry - qy
        length = lx * lx + ly * ly
        if length < 1e-6:
            return self.angle
        return self.angle + config.SOFT_TILT * (lx * (oy - py) - ly * (ox - px)) / length

    def _recompute(self, keep_position: bool = True) -> None:
        """Пересчитывает массу, центр тяжести, момент инерции и жёсткость тела."""
        self._sync_soft()
        self._recompute_appetite()
        self._recompute_neighbourhood()
        self._recompute_bone_pieces()
        self._recompute_joints()
        if not self.alive_cells:
            self.mass = config.CELL_MASS
            self.inertia = 1.0
            self.radius = config.HEX_SIZE
            return

        weighted = [
            (*hexgrid.hex_to_pixel(c, config.HEX_SIZE), cell_mass(self.kind_of(c)))
            for c in self.alive_cells
        ]
        total_mass = sum(m for _, _, m in weighted)
        new_com_x = sum(px * m for px, _, m in weighted) / total_mass
        new_com_y = sum(py * m for _, py, m in weighted) / total_mass

        if keep_position:
            # Центр тяжести уехал — сдвигаем тело так, чтобы клетки визуально
            # остались на своих местах.
            dx, dy = rotate(new_com_x - self.com_x, new_com_y - self.com_y, self.angle)
            self.x += dx
            self.y += dy

        self.com_x, self.com_y = new_com_x, new_com_y
        self.mass = total_mass

        inertia = 0.0
        radius = 0.0
        for px, py, m in weighted:
            dx, dy = px - new_com_x, py - new_com_y
            inertia += m * (dx * dx + dy * dy) + m * config.HEX_SIZE**2 * 0.5
            radius = max(radius, math.hypot(dx, dy))
        self.inertia = max(inertia, 1.0)
        # запас на изгиб: иначе согнутая клетка вылезет за границу мира
        self.radius = radius + config.CELL_RADIUS + config.SOFT_MAX_OFFSET
        self._recompute_transmit()

    def _recompute_bone_pieces(self) -> None:
        """Разбивает кости на куски: стоящие вплотную — это одна цельная кость.

        Мозг в кусок не входит, хотя и считается твёрдым: иначе приросшая к
        нему кость приварилась бы к неподвижной точке и перестала бы двигаться.
        Мозг держит её обычной жёсткой связью — то есть как сустав.
        """
        bones = {c for c in self.alive_cells if c != ROOT and self.kind_of(c) == BONE}
        self.bone_pieces = []
        while bones:
            queue = deque([bones.pop()])
            piece = [queue[0]]
            while queue:
                current = queue.popleft()
                for n in hexgrid.neighbors(current):
                    if n in bones:
                        bones.discard(n)
                        piece.append(n)
                        queue.append(n)
            if len(piece) > 1:  # одиночная кость и так жёсткая, ей кусок не нужен
                self.bone_pieces.append(piece)

    def _solve_bone_pieces(self) -> None:
        """Возвращает каждому костяному куску его форму из чертежа.

        Кусок при этом свободно едет и поворачивается — жёсткость только
        внутренняя. Середину куска не сдвигаем, поэтому сам по себе пересчёт
        тело никуда не толкает.
        """
        for piece in self.bone_pieces:
            count = len(piece)
            now = [self.local_pos(c) for c in piece]
            rest = [self.rest_pos(c) for c in piece]
            now_cx = sum(p[0] for p in now) / count
            now_cy = sum(p[1] for p in now) / count
            rest_cx = sum(p[0] for p in rest) / count
            rest_cy = sum(p[1] for p in rest) / count

            # каким поворотом чертёж лучше всего ложится на нынешнее положение
            cross = dot = 0.0
            for (nx, ny), (rx, ry) in zip(now, rest):
                ax, ay = rx - rest_cx, ry - rest_cy
                bx, by = nx - now_cx, ny - now_cy
                cross += ax * by - ay * bx
                dot += ax * bx + ay * by
            angle = math.atan2(cross, dot)

            for coord, (rx, ry) in zip(piece, rest):
                tx, ty = rotate(rx - rest_cx, ry - rest_cy, angle)
                tx += now_cx
                ty += now_cy
                base_x, base_y = self.rest_pos(coord)
                off = self.offsets[coord]
                stiff = config.BONE_PIECE_STIFF
                off[0] += (tx - base_x - off[0]) * stiff
                off[1] += (ty - base_y - off[1]) * stiff

    def _recompute_joints(self) -> None:
        """Суставы тела: клетка и два её соседа, стоящие по разные стороны.

        Именно в таком месте тело и складывается, поэтому угол держим здесь.
        Считаем список редко — только при перестройке тела.
        """
        self.joints = []
        directions = hexgrid.DIRECTIONS
        for coord in self.alive_cells:
            for i in range(3):
                a = (coord[0] + directions[i][0], coord[1] + directions[i][1])
                b = (coord[0] + directions[i + 3][0], coord[1] + directions[i + 3][1])
                if a in self.alive_cells and b in self.alive_cells:
                    self.joints.append((a, coord, b))

    def _solve_joints(self) -> None:
        """Держит суставы разогнутыми — распоркой через сустав.

        Если тело складывается, соседи по разные стороны от клетки сходятся;
        распорка между ними этому мешает, и тяга расходится по всему телу
        плавной дугой, вместо того чтобы сломать тело в одной точке.
        """
        for a, c, b in self.joints:
            stiff = (
                config.SOFT_JOINT_BONE
                if self.is_hard(a) and self.is_hard(c) and self.is_hard(b)
                else config.SOFT_JOINT_SKIN
            )
            rax, ray = self.rest_pos(a)
            rbx, rby = self.rest_pos(b)
            self._solve_brace(a, b, math.hypot(rbx - rax, rby - ray), stiff)

    def _solve_brace(self, a: Coord, b: Coord, rest: float, stiffness: float) -> None:
        """Распорка: обычное расстояние, но одинаково упругая в обе стороны."""
        oa, ob = self.offsets[a], self.offsets[b]
        ax, ay = self.rest_pos(a)
        bx, by = self.rest_pos(b)
        dx = (bx + ob[0]) - (ax + oa[0])
        dy = (by + ob[1]) - (ay + oa[1])
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return
        wa = 0.0 if a == ROOT else 1.0 / cell_mass(self.kind_of(a))
        wb = 0.0 if b == ROOT else 1.0 / cell_mass(self.kind_of(b))
        total = wa + wb
        if total <= 0.0:
            return
        error = (dist - rest) * stiffness / total
        cx, cy = dx / dist * error, dy / dist * error
        oa[0] += cx * wa
        oa[1] += cy * wa
        ob[0] -= cx * wb
        ob[1] -= cy * wb

    def _recompute_neighbourhood(self) -> None:
        """Кто кому сосед по чертежу — считаем раз на перестройку тела.

        Нужно расталкиванию клеток: соседей трогать нельзя, их держит связь,
        а проверять это в самом горячем цикле дорого.
        """
        self._neighbourhood = {
            coord: {coord, *hexgrid.neighbors(coord)} for coord in self.alive_cells
        }

    def _sync_soft(self) -> None:
        """Заводит смещения новым клеткам и убирает у потерянных."""
        for coord in self.alive_cells:
            self.offsets.setdefault(coord, [0.0, 0.0])
            self.offset_vels.setdefault(coord, [0.0, 0.0])
        for coord in list(self.offsets):
            if coord not in self.alive_cells:
                del self.offsets[coord]
                del self.offset_vels[coord]
        for coord in list(self.work_time):
            if coord not in self.alive_cells:
                del self.work_time[coord]

    def _recompute_appetite(self) -> None:
        """Аппетит тела и размер бака: и то, и другое — от живых клеток.

        Тело меньше — и ест меньше, и бак у него меньше, поэтому лишняя энергия
        при потере клеток пропадает.
        """
        self.appetite = sum(cell_upkeep(self.kind_of(c), c == ROOT) for c in self.alive_cells)
        self.max_energy = self.appetite * config.ENERGY_RESERVE
        # во время линьки бак сжимается, а плата за новые клетки ещё в нём —
        # обрезать энергию нельзя, иначе рост сразу встанет
        if not self.evolving:
            self.energy = min(self.energy, self.max_energy)

    def _recompute_transmit(self) -> None:
        """Какая доля толчка клетки доходит до тела.

        Считаем по самому твёрдому пути от мозга: цепочка костей передаёт
        толчок целиком, длинная кожаная ножка — почти нет.
        """
        best: dict[Coord, float] = {}
        if ROOT in self.alive_cells:
            best[ROOT] = 1.0
            queue = deque([ROOT])
            while queue:
                current = queue.popleft()
                for n in hexgrid.neighbors(current):
                    if n not in self.alive_cells:
                        continue
                    value = best[current] * link_transmit(self.is_hard(current), self.is_hard(n))
                    if value > best.get(n, 0.0) + 1e-6:
                        best[n] = value
                        queue.append(n)
        self.transmit = {
            c: max(config.SOFT_MIN_TRANSMIT, min(1.0, best.get(c, 0.0))) for c in self.alive_cells
        }

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

    def processors(self) -> list[Coord]:
        """Живые переработчики: только они добывают энергию из обломков."""
        return [
            coord
            for coord, spec in self.blueprint.cells.items()
            if spec.kind == PROCESSOR and coord in self.alive_cells
        ]

    def eyes(self) -> list[Coord]:
        """Живые зрительные клетки: каждая расширяет обзор камеры игрока."""
        return [
            coord
            for coord, spec in self.blueprint.cells.items()
            if spec.kind == EYE and coord in self.alive_cells
        ]

    def eye_aim(
        self,
        coord: Coord,
        foods: list[tuple[float, float]],
        bodies: list[tuple[float, float]],
    ) -> tuple[float, float] | None:
        """Куда смотрит живой глаз: единичный вектор в осях мира или ничего.

        Стороны света всегда видны. Еду и врага — только в пределах
        `EYE_SENSE_RANGE` клеток от этой клетки.
        """
        spec = self.blueprint.cells.get(coord)
        if spec is None or spec.kind != EYE or coord not in self.alive_cells:
            return None
        compass = EYE_LOOK_VECTORS.get(spec.look)
        if compass is not None:
            return compass
        origin = self.cell_world_pos(coord)
        points = foods if spec.look == LOOK_FOOD else bodies
        best: tuple[float, float] | None = None
        best_d: int | None = None
        for px, py in points:
            hq, hr = hexgrid.pixel_to_hex(px - origin[0], py - origin[1], config.HEX_SIZE)
            dist = hexgrid.distance((0, 0), (hq, hr))
            if dist > config.EYE_SENSE_RANGE:
                continue
            if best_d is None or dist < best_d:
                best = (px, py)
                best_d = dist
        if best is None:
            return None
        dx = best[0] - origin[0]
        dy = best[1] - origin[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return None
        return dx / length, dy / length

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
            # Потеряли мозг — разваливается всё остальное.
            lost.extend(self.alive_cells)
            self.alive_cells = set()
        self._recompute()
        return lost

    def _next_hole(self) -> Coord | None:
        """Какую дырку зарастим следующей — ближайшую к мозгу."""
        candidates = [
            c
            for c in self.blueprint.cells
            if c not in self.alive_cells
            and (not self.alive_cells or any(n in self.alive_cells for n in hexgrid.neighbors(c)))
        ]
        if not candidates:
            return None
        # при линьке сначала даровые дырки прошлого этапа, потом платные новые
        return min(
            candidates,
            key=lambda c: (
                0 if self.evolving and c in self._molt_from else 1,
                hexgrid.distance(ROOT, c),
                c,
            ),
        )

    def heal_one(self) -> bool:
        """Отращивает одну клетку за энергию: столько же, сколько стоит постройка."""
        coord = self._next_hole()
        if coord is None:
            return False
        # дырка прошлого этапа при линьке зарастает даром; новая клетка — за очки
        if self.evolving and coord in self._molt_from:
            price = 0
        else:
            price = cell_cost(self.kind_of(coord))
        if self.energy < price:
            return False
        self.energy -= price
        self.alive_cells.add(coord)
        self._recompute()
        self._finish_evolve_if_grown()
        return True

    def heal(self, count: int = 1) -> int:
        """Возвращает утраченные клетки. Расти сверх чертежа нельзя."""
        healed = 0
        for _ in range(count):
            if not self.heal_one():
                break
            healed += 1
        return healed

    def repair(self, dt: float) -> int:
        """Ремонт, пока держат кнопку: клетки отрастают по REPAIR_RATE в секунду."""
        self.repair_progress += config.REPAIR_RATE * dt
        grown = 0
        while self.repair_progress >= 1.0:
            if not self.heal_one():
                # чинить нечего или не на что — накопленное не копим впрок
                self.repair_progress = 0.0
                break
            self.repair_progress -= 1.0
            grown += 1
        return grown

    def stop_repair(self) -> None:
        """Кнопку отпустили — недокопленный прогресс пропадает."""
        self.repair_progress = 0.0

    def heal_full(self) -> None:
        """Чит: мгновенно и бесплатно возвращает все клетки чертежа."""
        self.alive_cells = set(self.blueprint.cells)
        self._recompute()
        self._finish_evolve_if_grown()

    def next_evolve_cost(self) -> int | None:
        """Плата за переход на следующий этап или None, если расти больше некуда."""
        if self.species is None or self.evolving:
            return None
        nxt = self.stage_index + 1
        if nxt >= len(self.species.stages):
            return None
        return evolve_cost(self.species.stages[self.stage_index], self.species.stages[nxt])

    def shed_for_next(self) -> list[Coord]:
        """Сбрасывает клетки, которых нет в следующем этапе. Чертёж ещё старый."""
        if self.species is None:
            return []
        nxt = self.species.stages[self.stage_index + 1]
        extra = [c for c in list(self.alive_cells) if c not in nxt.cells]
        for coord in extra:
            self.alive_cells.discard(coord)
        # линька уже началась: бак сожмётся, плату за рост резать нельзя
        self.evolving = True
        self._recompute()
        return extra

    def start_growing_next(self) -> None:
        """Чертёж становится следующим этапом; рост идёт сам, как ремонт."""
        assert self.species is not None
        previous = self.species.stages[self.stage_index]
        nxt = self.species.stages[self.stage_index + 1]
        old_muscles = {frozenset((m.a, m.b)) for m in previous.muscles}
        muscle_price = sum(m.cost() for m in nxt.muscles if frozenset((m.a, m.b)) not in old_muscles)
        self.energy = max(0.0, self.energy - muscle_price)
        self._molt_from = set(previous.cells)
        self.evolving = True
        self.blueprint = nxt.copy()
        self.repair_progress = 0.0
        self._recompute()
        self._finish_evolve_if_grown()

    def _finish_evolve_if_grown(self) -> None:
        if not self.evolving:
            return
        if any(c not in self.alive_cells for c in self.blueprint.cells):
            return
        self.evolving = False
        self.stage_index += 1
        self._molt_from = set()
        self.energy = min(self.energy, self.max_energy)

    # --- энергия и голод ---

    def eat(self, energy: float) -> bool:
        """Съедает обломок. Сытое существо (полный бак) еду не трогает."""
        if self.energy >= self.max_energy:
            return False
        self.energy = min(self.max_energy, self.energy + energy)
        return True

    def reset_hunger(self) -> None:
        """Заводит таймер до следующего удара голода — каждый раз новый."""
        rng = self.rng if self.rng is not None else random
        self.hunger_timer = rng.uniform(config.HUNGER_PERIOD_MIN, config.HUNGER_PERIOD_MAX)
        self.since_hunger = 0.0
        self.work_time.clear()
        self.muscle_work.clear()
        self.photo_upkeep = {
            c: (1.0 if rng.random() < config.PHOTOSYNTH_UPKEEP_CHANCE else 0.0)
            for c in self.alive_cells
            if self.kind_of(c) == PHOTOSYNTH
        }

    @property
    def hunger_due(self) -> bool:
        return self.hunger_timer <= 0.0

    def cell_demand(self, coord: Coord) -> float:
        """Сколько энергии просит клетка за нынешний удар голода.

        Работающей клетке (двигатель жжёт топливо, переработчик топит обломки)
        считаем по доле времени: работала полинтервала — заплатит середину
        между «стояла» и «работала».
        """
        kind = self.kind_of(coord)
        if kind == PHOTOSYNTH:
            return self.photo_upkeep.get(coord, 0.0)
        demand = cell_upkeep(kind, coord == ROOT)
        if coord != ROOT and self.since_hunger > 0.0:
            extra = cell_work_upkeep(kind) - cell_upkeep(kind)
            if extra > 0.0:
                share = min(1.0, self.work_time.get(coord, 0.0) / self.since_hunger)
                demand += extra * share
        return demand

    def muscle_demand(self) -> float:
        """Аппетит мышц: только за то время, что они реально тянули."""
        if self.since_hunger <= 0.0:
            return 0.0
        total = 0.0
        for index, worked in self.muscle_work.items():
            if index >= len(self.blueprint.muscles):
                continue
            share = min(1.0, worked / self.since_hunger)
            total += self.blueprint.muscles[index].work_upkeep() * share
        return total

    def demand(self) -> float:
        """Сколько энергии тело просит целиком за нынешний удар голода."""
        return sum(self.cell_demand(c) for c in self.alive_cells) + self.muscle_demand()

    def starve(self) -> list[Coord]:
        """Удар голода: кормит клетки, а на кого не хватило — те отваливаются.

        Объедаемся с краёв: первой уходит самая дальняя от мозга клетка. Мозг
        ест последним, и если даже голому мозгу не хватило — это смерть.
        Возвращает всё потерянное — из этого получится еда.
        """
        lost: list[Coord] = []
        photo_count = sum(1 for c in self.alive_cells if self.kind_of(c) == PHOTOSYNTH)
        if photo_count:
            gain = config.PHOTOSYNTH_ENERGY_GAIN * photo_count
            self.energy = min(self.max_energy, self.energy + gain)
        while self.energy < self.demand():
            victims = [c for c in self.alive_cells if c != ROOT]
            if not victims:
                lost.extend(self.remove_cell(ROOT))
                break
            victim = max(victims, key=lambda c: (hexgrid.distance(ROOT, c), c))
            lost.extend(self.remove_cell(victim))
        if not self.is_dead:
            self.energy = max(0.0, self.energy - self.demand())
        self.reset_hunger()
        return lost

    # --- физика ---

    def muscles_alive(self) -> list[tuple[int, Muscle]]:
        """Мышцы, у которых обе клетки-конца на месте."""
        return [
            (i, m)
            for i, m in enumerate(self.blueprint.muscles)
            if m.a in self.alive_cells and m.b in self.alive_cells
        ]

    def muscle_groups(self) -> set[int]:
        return {m.group for _, m in self.muscles_alive()}

    def apply_muscles(self, active_groups: set[int], dt: float) -> None:
        """Отмечает, какие мышцы сейчас тянут, и копит их наработку.

        Само стягивание делает `soft_step`: мышца не толкает тело напрямую,
        она сгибает его, а ход даёт уже вода, в которую упирается хвост.
        """
        self.pulling = set()
        for index, muscle in self.muscles_alive():
            if muscle.group not in active_groups:
                continue
            self.pulling.add(index)
            self.muscle_work[index] = self.muscle_work.get(index, 0.0) + dt

    def _solve_distance(
        self, a: Coord, b: Coord, rest: float, stiffness: float, limit: float | None = None
    ) -> None:
        """Сближает или разводит две клетки до нужного расстояния.

        `limit` — насколько сильно вообще позволено подвинуть за один проход;
        им ограничена мышца, чтобы её сила была силой, а не приказом.
        """
        oa, ob = self.offsets[a], self.offsets[b]
        ax, ay = self.rest_pos(a)
        bx, by = self.rest_pos(b)
        dx = (bx + ob[0]) - (ax + oa[0])
        dy = (by + ob[1]) - (ay + oa[1])
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return

        error = dist - rest
        if error < 0.0:
            # Клетки сошлись ближе положенного — это сжатие. Сминать легко,
            # но чем ближе к пределу, тем упорнее клетка упирается.
            squeezed = -error / rest if rest > 0.0 else 0.0
            tight = min(1.0, squeezed / config.SOFT_BURST)
            push = stiffness * config.SOFT_SQUEEZE_STIFF * (1.0 + 8.0 * tight * tight)
            error *= min(1.0, push)
        else:
            error *= stiffness
        if limit is not None:
            error = max(-limit, min(limit, error))

        wa = 0.0 if a == ROOT else 1.0 / cell_mass(self.kind_of(a))
        wb = 0.0 if b == ROOT else 1.0 / cell_mass(self.kind_of(b))
        total = wa + wb
        if total <= 0.0:
            return
        cx = dx / dist * error / total
        cy = dy / dist * error / total
        oa[0] += cx * wa
        oa[1] += cy * wa
        ob[0] -= cx * wb
        ob[1] -= cy * wb

    def _solve_self_collisions(self) -> None:
        """Клетки одного тела не лезут друг в друга.

        Соседей по чертежу держит связь, поэтому расталкиваем только тех, кто
        соседями не является, а сошёлся вплотную. Чтобы не перебирать все пары,
        раскладываем клетки по корзинам размером с клетку и смотрим только
        соседние корзины.
        """
        cell = config.SELF_RADIUS
        buckets: dict[tuple[int, int], list[tuple[Coord, float, float]]] = {}
        for coord in self.alive_cells:
            px, py = self.local_pos(coord)
            key = (int(px // cell), int(py // cell))
            buckets.setdefault(key, []).append((coord, px, py))

        near = self._neighbourhood
        for (bx, by), here in buckets.items():
            for dx, dy in ((0, 0), (1, -1), (1, 0), (1, 1), (0, 1)):
                there = buckets.get((bx + dx, by + dy))
                if not there:
                    continue
                same = dx == 0 and dy == 0
                for i, (a, ax, ay) in enumerate(here):
                    skip = near[a]
                    for b, cx, cy in (here[i + 1 :] if same else there):
                        if b in skip:
                            continue  # соседей по чертежу держит связь
                        gap_x, gap_y = cx - ax, cy - ay
                        dist = math.hypot(gap_x, gap_y)
                        if dist >= cell or dist < 1e-6:
                            continue
                        self._push_apart(a, b, gap_x, gap_y, dist, cell - dist)

    def _push_apart(
        self, a: Coord, b: Coord, dx: float, dy: float, dist: float, overlap: float
    ) -> None:
        """Разводит две налезшие клетки — поровну по массе, в разные стороны."""
        wa = 0.0 if a == ROOT else 1.0 / cell_mass(self.kind_of(a))
        wb = 0.0 if b == ROOT else 1.0 / cell_mass(self.kind_of(b))
        total = wa + wb
        if total <= 0.0:
            return
        push = overlap * config.SELF_PUSH / total
        cx, cy = dx / dist * push, dy / dist * push
        oa, ob = self.offsets[a], self.offsets[b]
        oa[0] -= cx * wa
        oa[1] -= cy * wa
        ob[0] += cx * wb
        ob[1] += cy * wb

    def _tear(self, coord: Coord) -> None:
        """Помечает клетку как оторвавшуюся. Твёрдое так не теряют."""
        if coord != ROOT and not self.is_hard(coord) and coord not in self.torn:
            self.torn.append(coord)

    def _joint_bend(self, coord: Coord) -> float:
        """Насколько сустав в этой клетке сложился против чертежа, в радианах.

        Берём пары соседей и смотрим, как изменился угол между ними: плавная
        дуга даёт мало, сложенное вдвое тело — много.
        """
        live = [n for n in hexgrid.neighbors(coord) if n in self.alive_cells]
        if len(live) < 2:
            return 0.0
        cx, cy = self.local_pos(coord)
        rx, ry = self.rest_pos(coord)
        worst = 0.0
        for i, first in enumerate(live):
            fx, fy = self.local_pos(first)
            frx, fry = self.rest_pos(first)
            for second in live[i + 1 :]:
                sx, sy = self.local_pos(second)
                srx, sry = self.rest_pos(second)
                now = _angle_between(fx - cx, fy - cy, sx - cx, sy - cy)
                rest = _angle_between(frx - rx, fry - ry, srx - rx, sry - ry)
                worst = max(worst, abs(rest - now))
        return worst

    def _recompute_squeeze(self) -> None:
        """Насколько клетку смяло или растянуло и вдоль какой оси.

        Смотрим на связи с соседями: укоротилась связь — клетку с этой стороны
        придавило (плюс), растянулась — клетка вытягивается вслед за ней и
        закрывает собой щель (минус). Кость не деформируется вовсе.
        """
        self.squeeze = {}
        for coord in self.alive_cells:
            if self.is_hard(coord):
                self.squeeze[coord] = (0.0, 0.0)
                continue
            worst = 0.0
            axis = 0.0
            ax, ay = self.local_pos(coord)
            for n in hexgrid.neighbors(coord):
                if n not in self.alive_cells:
                    continue
                bx, by = self.local_pos(n)
                dx, dy = bx - ax, by - ay
                dist = math.hypot(dx, dy)
                amount = (config.HEX_STEP - dist) / config.HEX_STEP
                if abs(amount) > abs(worst):
                    worst = amount
                    axis = math.atan2(dy, dx)
            worst = max(-config.SOFT_STRETCH_MAX, min(1.0, worst))
            self.squeeze[coord] = (worst, axis)
            if worst >= config.SOFT_BURST and coord not in self.torn:
                self.torn.append(coord)  # смяло до предела — клетка лопнула

    def squeeze_at(self, coord: Coord) -> float:
        """Как деформирована клетка: плюс — смяло, минус — растянуло."""
        return self.squeeze.get(coord, (0.0, 0.0))[0]

    def water_step(self, dt: float) -> None:
        """Вода цепляется за каждую клетку отдельно.

        Клетка, идущая поперёк тела, гребёт сильнее той, что идёт вдоль, —
        поэтому виляние хвостом даёт ход. Сопротивление всегда направлено
        против движения клетки, так что само по себе разогнать оно не может.
        """
        if not self.alive_cells:
            return
        fx = fy = torque = 0.0
        # Пока мышцы тянут, гребок плавника асимметричен: разгонять тело
        # легче, чем тормозить или сдавать назад тем же взмахом. Без работы
        # мышц вода ведёт себя как раньше — это только про сам гребок.
        if self.pulling:
            speed = math.hypot(self.vx, self.vy)
            if speed > 1.0:
                fwd_x, fwd_y = self.vx / speed, self.vy / speed
            else:
                fwd_x, fwd_y = rotate(1.0, 0.0, self.angle)
        for coord in self.alive_cells:
            vx, vy = self.cell_velocity(coord)
            if vx == 0.0 and vy == 0.0:
                continue
            ax, ay = self._cell_axis(coord)
            along = vx * ax + vy * ay
            cross_x = vx - along * ax
            cross_y = vy - along * ay
            # быстрый гребок цепляет воду сильнее, чем медленный возврат
            cross = math.hypot(cross_x, cross_y)
            cross_drag = config.WATER_CROSS_DRAG + config.WATER_QUAD_DRAG * cross
            if self.pulling:
                thrust_x, thrust_y = -cross_x * cross_drag, -cross_y * cross_drag
                mult = (
                    config.WATER_FIN_ACCEL_MULT
                    if thrust_x * fwd_x + thrust_y * fwd_y > 0.0
                    else config.WATER_FIN_BRAKE_MULT
                )
                cross_drag *= mult
            along_drag = config.WATER_ALONG_DRAG + config.WATER_QUAD_DRAG * abs(along)
            dfx = -(along * ax * along_drag + cross_x * cross_drag)
            dfy = -(along * ay * along_drag + cross_y * cross_drag)
            ox, oy = self.cell_offset(coord)
            fx += dfx
            fy += dfy
            torque += ox * dfy - oy * dfx

            # Клетка тормозится о воду и сама по себе, иначе получится цикл:
            # вода тормозит тело, мясо по инерции уезжает вперёд и через ту же
            # воду подталкивает тело обратно — вечный двигатель.
            vel = self.offset_vels.get(coord)
            if vel is not None:
                lx, ly = rotate(dfx, dfy, -self.angle)
                push = dt / cell_mass(self.kind_of(coord))
                vel[0] += lx * push
                vel[1] += ly * push

        dvx = fx / self.mass * dt
        dvy = fy / self.mass * dt
        dspin = torque / self.inertia * dt
        self.vx += dvx
        self.vy += dvy
        self.spin += dspin
        # Торможение о воду — не рывок тела: мясо его уже пережило само,
        # поэтому из отставания эту часть надо вычесть.
        self._water_dv = (dvx, dvy, dspin)

    def _cell_axis(self, coord: Coord) -> tuple[float, float]:
        """Куда «вдоль тела» смотрит клетка — в мировых осях.

        Направление на соседа и направление от него — одна и та же ось, поэтому
        складывать их напрямую нельзя (взаимно погасятся). Складываем удвоенные
        углы: так «влево» и «вправо» дают одну ось, а не ноль.
        """
        sx = sy = 0.0
        cx, cy = self.local_pos(coord)
        for n in hexgrid.neighbors(coord):
            if n not in self.alive_cells:
                continue
            nx, ny = self.local_pos(n)
            angle = math.atan2(ny - cy, nx - cx)
            sx += math.cos(2.0 * angle)
            sy += math.sin(2.0 * angle)
        if math.hypot(sx, sy) < 1e-6:
            return rotate(1.0, 0.0, self.angle)
        axis = math.atan2(sy, sx) / 2.0
        return rotate(math.cos(axis), math.sin(axis), self.angle)

    def _thruster_heat_step(self, active_groups: set[int], dt: float) -> set[int]:
        """Перегрев двигателей игрока: держишь кнопку долго — она копит жар
        и ненадолго отключается, остальные кнопки это не трогает.
        """
        active = set(active_groups)
        for group in {spec.group for spec in self.thrusters()}:
            cooldown = self.thruster_cooldown.get(group, 0.0)
            if cooldown > 0.0:
                cooldown = max(0.0, cooldown - dt)
                self.thruster_cooldown[group] = cooldown
                self.thruster_heat[group] = cooldown / config.THRUSTER_COOLDOWN_TIME
                self.thruster_idle[group] = 0.0
                active.discard(group)
            elif group in active:
                self.thruster_idle[group] = 0.0
                heat = self.thruster_heat.get(group, 0.0) + dt / config.THRUSTER_OVERHEAT_TIME
                if heat >= 1.0:
                    self.thruster_heat[group] = 1.0
                    self.thruster_cooldown[group] = config.THRUSTER_COOLDOWN_TIME
                    active.discard(group)  # перегрелась прямо сейчас — толчка в этом кадре нет
                else:
                    self.thruster_heat[group] = heat
            else:
                # жар не начинает падать, пока пауза не стала заметной — иначе
                # частое дёрганье кнопки вообще не даёт ему накопиться
                idle = self.thruster_idle.get(group, 0.0) + dt
                self.thruster_idle[group] = idle
                if idle >= config.THRUSTER_COOL_GRACE:
                    self.thruster_heat[group] = max(
                        0.0, self.thruster_heat.get(group, 0.0) - dt / config.THRUSTER_COOL_RATE
                    )
        return active

    def apply_thrust(self, active_groups: set[int], dt: float) -> None:
        """Толкает тело. Через мягкую ножку доходит не всё.

        Часть силы уходит впустую и лишь сгибает саму ножку — как грести
        веслом в киселе. Костяной скелет от мозга к двигателю передаёт толчок
        целиком, ради этого кость и ставят.
        """
        if self.is_player:
            active_groups = self._thruster_heat_step(active_groups, dt)
        thrust_force = config.PLAYER_THRUST_FORCE if self.is_player else config.THRUST_FORCE
        fx = fy = torque = 0.0
        for spec in self.thrusters():
            if spec.group not in active_groups:
                continue
            dx, dy = hexgrid.direction_vector(spec.direction)
            share = self.transmit.get(spec.coord, 1.0)
            # работающий двигатель прожорливее — копим его наработку до голода
            self.work_time[spec.coord] = self.work_time.get(spec.coord, 0.0) + dt

            wx, wy = rotate(dx, dy, self.angle)
            wx *= thrust_force * share
            wy *= thrust_force * share
            ox, oy = self.cell_offset(spec.coord)
            fx += wx
            fy += wy
            torque += ox * wy - oy * wx

            vel = self.offset_vels.get(spec.coord)
            if vel is not None:
                # непереданная часть уходит в изгиб — в местных осях тела
                push = thrust_force * (1.0 - share) / cell_mass(spec.kind) * dt
                vel[0] += dx * push
                vel[1] += dy * push

        self.vx += fx / self.mass * dt
        self.vy += fy / self.mass * dt
        self.spin += torque / self.inertia * dt

    def soft_step(self, dt: float) -> None:
        """Пересчитывает изгиб тела и собирает клетки, которые перегнуло.

        Сначала «мясо» отстаёт от рывка тела, потом клетки подтягиваются к
        своим местам и друг к другу. Изгиб — это положение клеток: он меняет
        вид, точки касания и плечи ударов, но сам по себе тело не разгоняет.
        """
        self.torn = []
        if dt <= 0.0 or not self.alive_cells:
            return

        # 1. Тело дёрнулось (тяга, удар, торможение) — мягкие клетки за ним не
        # поспевают. Ровным ходом тело не дёргается, и хвост распрямляется.
        water_dvx, water_dvy, water_dspin = self._water_dv
        self._water_dv = (0.0, 0.0, 0.0)
        dvx = self.vx - self._prev_vx - water_dvx
        dvy = self.vy - self._prev_vy - water_dvy
        dspin = self.spin - self._prev_spin - water_dspin
        self._prev_vx, self._prev_vy, self._prev_spin = self.vx, self.vy, self.spin
        lag_x, lag_y = rotate(dvx, dvy, -self.angle)
        lag_x *= config.SOFT_INERTIA
        lag_y *= config.SOFT_INERTIA
        dspin *= config.SOFT_INERTIA
        damping = math.exp(-config.SOFT_DAMPING * dt)
        previous: dict[Coord, tuple[float, float]] = {}

        for coord in self.alive_cells:
            off = self.offsets[coord]
            vel = self.offset_vels[coord]
            previous[coord] = (off[0], off[1])
            lx, ly = self.rest_pos(coord)
            vel[0] = vel[0] * damping - lag_x + dspin * ly
            vel[1] = vel[1] * damping - lag_y - dspin * lx
            off[0] += vel[0] * dt
            off[1] += vel[1] * dt

        # 2. Клетки тянутся на свои места и держат расстояние друг до друга.
        # Расстояние можно укоротить — отсюда и сжатие, и бегущая по хвосту
        # волна: соседи передают движение с задержкой.
        links = [
            (a, b)
            for a in self.alive_cells
            for b in hexgrid.neighbors(a)
            if b in self.alive_cells and a < b
        ]
        muscle_step = config.MUSCLE_FORCE * dt * dt / config.SOFT_ITERATIONS

        for step in range(config.SOFT_ITERATIONS):
            for coord in self.alive_cells:
                if coord == ROOT:
                    continue
                off = self.offsets[coord]
                anchor = config.SOFT_ANCHOR_BONE if self.is_hard(coord) else config.SOFT_ANCHOR_SKIN
                off[0] -= off[0] * anchor
                off[1] -= off[1] * anchor

            for index in self.pulling:
                muscle = self.blueprint.muscles[index]
                if muscle.a not in self.offsets or muscle.b not in self.offsets:
                    continue
                # Мышца тянет концы вместе — но не приказом, а силой: за проход
                # она может подтянуть их лишь настолько, насколько хватает сил.
                self._solve_distance(muscle.a, muscle.b, 0.0, 1.0, limit=muscle_step * muscle.strength)

            # суставы держат свои углы: тело выгибается дугой, а не ломается
            self._solve_joints()

            # кость держит свою форму: кусок целиком встаёт как в чертеже,
            # но ехать и поворачиваться ему никто не мешает
            self._solve_bone_pieces()

            # расталкивание дорогое, а дело не срочное: хватит и через раз
            if step % 2 == 1:
                self._solve_self_collisions()

            # связи держат расстояния и говорят последнее слово: что бы ни
            # натворили мышцы, суставы и расталкивание — щелей быть не должно
            for a, b in links:
                self._solve_distance(
                    a, b, config.HEX_STEP, link_stiffness(self.is_hard(a), self.is_hard(b))
                )

            if ROOT in self.offsets:
                self.offsets[ROOT][0] = self.offsets[ROOT][1] = 0.0

        # 3. Что не выдержало. Свернуться крутой дугой можно, а вот растащить
        # соседей или сложить сустав вдвое — уже разрыв.
        tear_at = config.HEX_STEP * config.SOFT_TEAR_STRETCH
        for a, b in links:
            ax, ay = self.local_pos(a)
            bx, by = self.local_pos(b)
            if math.hypot(bx - ax, by - ay) < tear_at:
                continue
            self._tear(max((a, b), key=lambda c: (hexgrid.distance(ROOT, c), c)))

        for coord in self.alive_cells:
            if self.is_hard(coord):
                continue  # кость не изламывается
            if self._joint_bend(coord) > config.SOFT_BEND_LIMIT:
                # ломается не сам сустав, а то, что за ним — дальше от мозга
                broken = [
                    n
                    for n in hexgrid.neighbors(coord)
                    if n in self.alive_cells
                    and hexgrid.distance(ROOT, n) > hexgrid.distance(ROOT, coord)
                ]
                self._tear(max(broken, default=coord))

        # 4. Скорости шевеления и предохранитель от улетевших клеток.
        for coord in self.alive_cells:
            off = self.offsets[coord]
            stretch = math.hypot(off[0], off[1])
            if stretch > config.SOFT_MAX_OFFSET:
                k = config.SOFT_MAX_OFFSET / stretch
                off[0] *= k
                off[1] *= k
            px, py = previous[coord]
            vel = self.offset_vels[coord]
            vel[0] = (off[0] - px) / dt
            vel[1] = (off[1] - py) / dt

        self._recompute_squeeze()

    def step(self, dt: float) -> None:
        self.soft_step(dt)

        # вода тормозит — и заодно даёт ход тому, кто ею гребёт
        self.water_step(dt)
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
        # сам удар голода наносит мир: объеденные клетки должны уплыть едой
        self.since_hunger += dt
        self.hunger_timer -= dt
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
