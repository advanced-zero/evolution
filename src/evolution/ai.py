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
    Muscle,
    cell_cost,
)

FORWARD = 1
TURN_LEFT = 2
TURN_RIGHT = 3


MUSCLE_LEFT = 4
MUSCLE_RIGHT = 5


def random_blueprint(points: int, rng: random.Random) -> Blueprint:
    """Случайное существо: комок клеток с двигателями по краям.

    `points` — бюджет постройки в очках, как у игрока. Часть врагов тратит
    его на скелет и получается меньше, зато твёрже, а часть вырастает угрями
    и плавает не тягой, а мышцами.
    """
    if points >= 16 and rng.random() < config.ENEMY_EEL_CHANCE:
        eel = eel_blueprint(points, rng)
        if eel is not None:
            return eel

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


def eel_blueprint(points: int, rng: random.Random) -> Blueprint | None:
    """Угорь: тело в два ряда и по мышце вдоль каждого бока.

    Мышца гнёт тело только тогда, когда идёт вдоль бока, а не по середине, —
    поэтому хребет отдельно, бока отдельно.
    """
    bp = Blueprint()
    # какие соседи считаются «левым» и «правым» боком — определяем по картинке,
    # а не по номерам направлений: так не запутаешься в осях
    sides = sorted(hexgrid.neighbors((0, 0)), key=lambda c: hexgrid.hex_to_pixel(c, 1.0)[1])
    left_step, right_step = sides[0], sides[-1]

    spine = [(0, 0)]
    left: list[tuple[int, int]] = []
    right: list[tuple[int, int]] = []
    # растим хребет с боками, пока хватает очков на тело и на две мышцы
    while len(spine) < 7:
        head = spine[-1]
        nxt = (head[0] - 1, head[1])
        l = (nxt[0] + left_step[0], nxt[1] + left_step[1])
        r = (nxt[0] + right_step[0], nxt[1] + right_step[1])
        if bp.cost() + 3 + 2 * len(spine) > points:
            break
        for coord in (nxt, l, r):
            bp.place(CellSpec(coord, SKIN))
        spine.append(nxt)
        left.append(l)
        right.append(r)

    if len(left) < 2:
        return None  # на угря не хватило — пусть будет обычное существо

    # сильнее враг себе не ставит: чрезмерная мышца рвёт собственный хвост
    strength = rng.randint(3, 6)
    bp.add_muscle(Muscle(left[0], left[-1], MUSCLE_LEFT, strength))
    bp.add_muscle(Muscle(right[0], right[-1], MUSCLE_RIGHT, strength))

    # пара двигателей на всякий случай: одними мышцами далеко не уедешь
    for coord in hexgrid.neighbors((0, 0)):
        if bp.can_place(coord) and bp.cost() + cell_cost(THRUSTER) <= points:
            bp.place(CellSpec(coord, THRUSTER, direction=0, group=FORWARD))
            break

    _grow_processors(bp, rng)
    return bp


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


def steer(creature: Creature, target_angle: float, phase: float = 0.0) -> set[int]:
    """Какие кнопки нажать, чтобы повернуться в нужную сторону и поехать."""
    active = _stroke(creature, target_angle, phase)

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


def _stroke(creature: Creature, target_angle: float, phase: float) -> set[int]:
    """Взмах хвостом: угорь жмёт мышцы боков попеременно, в такт.

    Чтобы повернуть, он дольше держит мышцу нужной стороны — тело выгибается
    в эту сторону и туда же уходит.
    """
    groups = sorted(creature.muscle_groups())
    if not groups:
        return set()

    err = _wrap(target_angle - creature.angle) - creature.spin * 0.35
    # перекос взмаха: в какую сторону поворачиваем, той стороне больше времени
    bias = max(-0.35, min(0.35, err * 0.4))
    beat = (phase % config.EEL_STROKE_PERIOD) / config.EEL_STROKE_PERIOD
    left = beat < 0.5 + bias
    half = groups[: max(1, len(groups) // 2)]
    other = groups[max(1, len(groups) // 2) :] or half
    return set(half if left else other)


def _nearest_food(me: Creature, foods: list) -> object | None:
    """Ближайший обломок в поле зрения — за ним и поплывём, когда голодно."""
    best = None
    best_distance = config.VISION_RADIUS
    for food in foods:
        distance = math.hypot(food.x - me.x, food.y - me.y)
        if distance < best_distance:
            best, best_distance = food, distance
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
        self.phase = rng.uniform(0.0, config.EEL_STROKE_PERIOD)  # такт взмаха хвостом

    def think(
        self,
        me: Creature,
        player: Creature | None,
        foods: list | None = None,
        dt: float = 0.0,
    ) -> set[int]:
        self.wander_timer -= dt
        self.backoff_timer = max(0.0, self.backoff_timer - dt)
        self.phase += dt

        beaten = len(me.alive_cells) < len(me.blueprint.cells) * config.ENEMY_FLEE_RATIO
        hungry = me.max_energy > 0.0 and me.energy < me.max_energy * config.ENEMY_HUNGRY_RATIO

        if player is not None and not player.is_dead:
            dx, dy = player.x - me.x, player.y - me.y
            distance = math.hypot(dx, dy)
            if distance < config.VISION_RADIUS:
                # от тела осталась половина — не до драки, надо уносить мозг
                if beaten:
                    return steer(me, math.atan2(-dy, -dx), self.phase)
                if distance < me.radius + player.radius + 40.0 and self.backoff_timer <= 0.0:
                    # слишком близко — отходим, чтобы снова разогнаться
                    self.backoff_timer = self.rng.uniform(0.7, 1.3)
                if self.backoff_timer > 0.0:
                    return steer(me, math.atan2(-dy, -dx), self.phase)
                return steer(me, math.atan2(dy, dx), self.phase)

        # голодному еда важнее прогулки — и залатать дырки тоже нужна энергия
        if (hungry or beaten) and foods:
            food = _nearest_food(me, foods)
            if food is not None:
                dx, dy = food.x - me.x, food.y - me.y
                # подошли вплотную — глушим двигатели и висим, пока не переварится
                if math.hypot(dx, dy) < config.PROCESS_RADIUS * 2.0:
                    return set()
                return steer(me, math.atan2(dy, dx), self.phase)

        if self.wander_timer <= 0.0:
            self.wander_target = (
                self.rng.uniform(0, config.WORLD_WIDTH),
                self.rng.uniform(0, config.WORLD_HEIGHT),
            )
            self.wander_timer = self.rng.uniform(3.0, 8.0)
        tx, ty = self.wander_target
        if math.hypot(tx - me.x, ty - me.y) < 150.0:
            self.wander_timer = 0.0
        return steer(me, math.atan2(ty - me.y, tx - me.x), self.phase)
