"""Враги: как они выглядят и как соображают.

ИИ жмёт те же самые «кнопки» (группы двигателей), что и игрок, — никаких
особых способностей у врагов нет.
"""

from __future__ import annotations

import math
import random

from evolution import config, hexgrid
from evolution.creature import (
    BONE,
    PROCESSOR,
    SKIN,
    THRUSTER,
    Blueprint,
    CellSpec,
    Creature,
    Species,
    cell_cost,
)
from evolution.food import Crumb

FORWARD = 1
TURN_LEFT = 2
TURN_RIGHT = 3


def random_blueprint(points: int, rng: random.Random) -> Blueprint:
    """Случайное существо: комок клеток с двигателями по краям.

    `points` — бюджет постройки в очках, как у игрока. Часть врагов тратит
    его на скелет и получается меньше, зато твёрже.
    """
    # очки на скелет откладываем заранее: со скелетом тело выходит мельче.
    # Костей не больше, чем позволяет размер, иначе от тела ничего не остаётся.
    bones = 0
    if rng.random() < config.ENEMY_BONE_CHANCE:
        bones = rng.randint(1, max(1, points // 7))
    body_points = max(6, points - bones * (cell_cost(BONE) - cell_cost(SKIN)))

    bp = Blueprint()
    while bp.cost() < body_points:
        base = rng.choice(list(bp.cells))
        spot = rng.choice(hexgrid.neighbors(base))
        if bp.can_place(spot):
            bp.place(CellSpec(spot, SKIN))

    # часть клеток превращаем в двигатели, сгруппированные по назначению
    coords = [c for c in bp.cells if c != (0, 0)]
    rng.shuffle(coords)
    wanted = max(2, len(coords) // 3)
    for coord in coords[:wanted]:
        spec = bp.cells[coord]
        spec.kind = THRUSTER
        spec.direction = 0  # все толкают «вперёд» — по местной оси +x
        px, py = hexgrid.hex_to_pixel(coord, 1.0)
        if abs(py) < 0.6:
            spec.group = FORWARD
        else:
            # двигатель сбоку разворачивает — какая сторона, туда и крутит
            spec.group = TURN_RIGHT if py > 0 else TURN_LEFT

    if bones:
        _grow_bones(bp, bones)
    _grow_processors(bp, rng)
    return bp


def _grow_stage(previous: Blueprint, budget: float, rng: random.Random) -> Blueprint:
    """Копия прошлого этапа, доращённая до бака — следующий возраст врага."""
    bp = previous.copy()
    guard = 0
    while bp.cost() + cell_cost(SKIN) <= budget + 1e-6 and guard < 80:
        guard += 1
        base = rng.choice(list(bp.cells))
        spot = rng.choice(hexgrid.neighbors(base))
        if bp.can_place(spot):
            bp.place(CellSpec(spot, SKIN))
    # новые кожи по краям часть делаем двигателями — иначе просто толстеет
    fresh = [c for c in bp.cells if c not in previous.cells]
    rng.shuffle(fresh)
    for coord in fresh[: max(0, len(fresh) // 3)]:
        spec = bp.cells[coord]
        spec.kind = THRUSTER
        spec.direction = 0
        px, py = hexgrid.hex_to_pixel(coord, 1.0)
        if abs(py) < 0.6:
            spec.group = FORWARD
        else:
            spec.group = TURN_RIGHT if py > 0 else TURN_LEFT
    if rng.random() < config.ENEMY_BONE_CHANCE:
        skin = [c for c in fresh if bp.cells[c].kind == SKIN]
        rng.shuffle(skin)
        for coord in skin:
            extra = cell_cost(BONE) - cell_cost(SKIN)
            if bp.cost() + extra > budget + 1e-6:
                break
            bp.cells[coord].kind = BONE
    return bp


def random_species(points: int, rng: random.Random) -> Species:
    """Враг с 1–3 этапами: первый как раньше, следующие — копия, выросшая до бака."""
    first = random_blueprint(points, rng)
    stages = [first]
    extra = rng.randint(0, 2)
    for _ in range(extra):
        budget = stages[-1].tank()
        nxt = _grow_stage(stages[-1], budget, rng)
        if nxt.cost() <= stages[-1].cost():
            break
        stages.append(nxt)
    return Species(stages)


def _grow_processors(bp: Blueprint, rng: random.Random) -> None:
    """Ставит 1–2 переработчика поближе к мозгу: без них врагу нечем есть."""
    skin = [coord for coord, spec in bp.cells.items() if spec.kind == SKIN and coord != (0, 0)]
    if not skin:
        return
    skin.sort(key=lambda c: hexgrid.distance((0, 0), c))
    wanted = min(len(skin), 1 if len(bp.cells) < 10 else rng.randint(1, 2))
    for coord in skin[:wanted]:
        bp.cells[coord].kind = PROCESSOR


def _grow_bones(bp: Blueprint, count: int) -> None:
    """Отращивает скелет: костенеет кожа впереди и ближе к мозгу.

    Спереди — потому что там таранят; у мозга — потому что от него жёсткость
    расходится по всему телу.
    """
    skin = [coord for coord, spec in bp.cells.items() if spec.kind == SKIN and coord != (0, 0)]
    skin.sort(key=lambda c: hexgrid.distance((0, 0), c) - hexgrid.hex_to_pixel(c, 1.0)[0])
    for coord in skin[:count]:
        bp.cells[coord].kind = BONE


def group_effects(creature: Creature) -> dict[int, tuple[float, float]]:
    """Что делает каждая группа двигателей: (тяга вперёд, крутящий момент).

    Двигатель на мягкой ножке считается слабее — иначе ИИ будет жать кнопки,
    которые на его вялом теле почти ничего не дают.
    """
    effects: dict[int, tuple[float, float]] = {}
    for spec in creature.thrusters():
        dx, dy = hexgrid.direction_vector(spec.direction)
        ox, oy = creature.local_pos(spec.coord)
        share = creature.transmit.get(spec.coord, 1.0)
        forward, torque = effects.get(spec.group, (0.0, 0.0))
        effects[spec.group] = (forward + dx * share, torque + (ox * dy - oy * dx) * share)
    return effects


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def steer(creature: Creature, target_angle: float) -> set[int]:
    """Какие кнопки нажать, чтобы повернуться в нужную сторону и поехать."""
    active: set[int] = set()

    effects = group_effects(creature)
    if not effects:
        return active

    err = _wrap(target_angle - creature.angle)
    # гасим уже набранное вращение, чтобы не крутиться волчком
    err -= creature.spin * 0.35

    if abs(err) > 0.12:
        sign = 1.0 if err > 0 else -1.0
        best = max(effects, key=lambda g: effects[g][1] * sign)
        if effects[best][1] * sign > 0.1:
            active.add(best)

    if abs(err) < 0.9:
        best = max(effects, key=lambda g: effects[g][0])
        if effects[best][0] > 0.1:
            active.add(best)

    return active


def _has_skin(me: Creature) -> bool:
    return any(me.kind_of(coord) == SKIN for coord in me.alive_cells)


def _nearest_food(me: Creature, foods: list, crumbs: list | None = None) -> object | None:
    """Ближайший обломок или крошка в поле зрения."""
    best = None
    best_distance = config.VISION_RADIUS
    for food in foods:
        distance = math.hypot(food.x - me.x, food.y - me.y)
        if distance < best_distance:
            best, best_distance = food, distance
    if crumbs and _has_skin(me):
        for crumb in crumbs:
            distance = math.hypot(crumb.x - me.x, crumb.y - me.y)
            if distance < best_distance:
                best, best_distance = crumb, distance
    return best


class EnemyBrain:
    """Простое поведение: бродит, ищет еду, таранит, а побитый — убегает."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.wander_target = (
            rng.uniform(0, config.WORLD_WIDTH),
            rng.uniform(0, config.WORLD_HEIGHT),
        )
        self.wander_timer = rng.uniform(2.0, 6.0)
        self.backoff_timer = 0.0

    def think(
        self,
        me: Creature,
        player: Creature | None,
        foods: list | None = None,
        dt: float = 0.0,
        crumbs: list | None = None,
    ) -> set[int]:
        self.wander_timer -= dt
        self.backoff_timer = max(0.0, self.backoff_timer - dt)

        beaten = len(me.alive_cells) < len(me.blueprint.cells) * config.ENEMY_FLEE_RATIO
        hungry = me.max_energy > 0.0 and me.energy < me.max_energy * config.ENEMY_HUNGRY_RATIO

        if player is not None and not player.is_dead:
            dx, dy = player.x - me.x, player.y - me.y
            distance = math.hypot(dx, dy)
            if distance < config.VISION_RADIUS:
                # от тела осталась половина — не до драки, надо уносить мозг
                if beaten:
                    return steer(me, math.atan2(-dy, -dx))
                if distance < me.radius + player.radius + 40.0 and self.backoff_timer <= 0.0:
                    # слишком близко — отходим, чтобы снова разогнаться
                    self.backoff_timer = self.rng.uniform(0.7, 1.3)
                if self.backoff_timer > 0.0:
                    return steer(me, math.atan2(-dy, -dx))
                return steer(me, math.atan2(dy, dx))

        # голодному еда важнее прогулки — и залатать дырки тоже нужна энергия
        if (hungry or beaten) and (foods or crumbs):
            food = _nearest_food(me, foods or [], crumbs)
            if food is not None:
                dx, dy = food.x - me.x, food.y - me.y
                # крошку надо коснуться кожей, целый обломок — переварить на месте
                halt = config.FOOD_CRUMB_RADIUS * 2.0 if isinstance(food, Crumb) else config.PROCESS_RADIUS * 2.0
                if math.hypot(dx, dy) < halt:
                    return set()
                return steer(me, math.atan2(dy, dx))

        if self.wander_timer <= 0.0:
            self.wander_target = (
                self.rng.uniform(0, config.WORLD_WIDTH),
                self.rng.uniform(0, config.WORLD_HEIGHT),
            )
            self.wander_timer = self.rng.uniform(3.0, 8.0)
        tx, ty = self.wander_target
        if math.hypot(tx - me.x, ty - me.y) < 150.0:
            self.wander_timer = 0.0
        return steer(me, math.atan2(ty - me.y, tx - me.x))
