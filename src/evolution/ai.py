"""Враги: как они выглядят и как соображают.

ИИ жмёт те же самые «кнопки» (группы двигателей), что и игрок, — никаких
особых способностей у врагов нет.
"""

from __future__ import annotations

import math
import random

from evolution import config, hexgrid
from evolution.creature import SKIN, THRUSTER, Blueprint, CellSpec, Creature

FORWARD = 1
TURN_LEFT = 2
TURN_RIGHT = 3


def random_blueprint(cell_count: int, rng: random.Random) -> Blueprint:
    """Случайное существо: комок клеток с двигателями по краям."""
    bp = Blueprint()
    while len(bp) < cell_count:
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
    return bp


def group_effects(creature: Creature) -> dict[int, tuple[float, float]]:
    """Что делает каждая группа двигателей: (тяга вперёд, крутящий момент)."""
    effects: dict[int, tuple[float, float]] = {}
    for spec in creature.thrusters():
        dx, dy = hexgrid.direction_vector(spec.direction)
        ox, oy = creature.local_pos(spec.coord)
        forward, torque = effects.get(spec.group, (0.0, 0.0))
        effects[spec.group] = (forward + dx, torque + ox * dy - oy * dx)
    return effects


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def steer(creature: Creature, target_angle: float) -> set[int]:
    """Какие кнопки нажать, чтобы повернуться в нужную сторону и поехать."""
    effects = group_effects(creature)
    if not effects:
        return set()

    err = _wrap(target_angle - creature.angle)
    # гасим уже набранное вращение, чтобы не крутиться волчком
    err -= creature.spin * 0.35
    active: set[int] = set()

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


class EnemyBrain:
    """Простое поведение: бродит, замечает игрока, разгоняется и таранит."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.wander_target = (
            rng.uniform(0, config.WORLD_WIDTH),
            rng.uniform(0, config.WORLD_HEIGHT),
        )
        self.wander_timer = rng.uniform(2.0, 6.0)
        self.backoff_timer = 0.0

    def think(self, me: Creature, player: Creature | None, dt: float) -> set[int]:
        self.wander_timer -= dt
        self.backoff_timer = max(0.0, self.backoff_timer - dt)

        if player is not None and not player.is_dead:
            dx, dy = player.x - me.x, player.y - me.y
            distance = math.hypot(dx, dy)
            if distance < config.VISION_RADIUS:
                if distance < me.radius + player.radius + 40.0 and self.backoff_timer <= 0.0:
                    # слишком близко — отходим, чтобы снова разогнаться
                    self.backoff_timer = self.rng.uniform(0.7, 1.3)
                if self.backoff_timer > 0.0:
                    return steer(me, math.atan2(-dy, -dx))
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
