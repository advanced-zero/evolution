"""Столкновения существ и отрыв клеток при таране."""

from __future__ import annotations

import math

from evolution import config
from evolution.creature import BONE, PHOTOSYNTH, Creature
from evolution.hexgrid import Coord

Hit = tuple[Creature, Coord]


def collide_pair(a: Creature, b: Creature) -> list[Hit]:
    """Сталкивает два существа. Возвращает клетки, которые надо оторвать."""
    dx = b.x - a.x
    dy = b.y - a.y
    if math.hypot(dx, dy) > a.radius + b.radius:
        return []  # даже близко не рядом

    contact = _find_contact(a, b)
    if contact is None:
        return []
    coord_a, coord_b, nx, ny, overlap = contact

    # смещения точки касания от центров тяжести
    rax, ray = a.cell_offset(coord_a)
    rbx, rby = b.cell_offset(coord_b)

    vax, vay = a.point_velocity(rax, ray)
    vbx, vby = b.point_velocity(rbx, rby)

    rel_n = (vbx - vax) * nx + (vby - vay) * ny
    if rel_n > 0:
        return []  # уже разлетаются

    ra_cross = rax * ny - ray * nx
    rb_cross = rbx * ny - rby * nx
    denom = 1.0 / a.mass + 1.0 / b.mass + ra_cross**2 / a.inertia + rb_cross**2 / b.inertia
    j = -(1.0 + config.RESTITUTION) * rel_n / denom

    a.vx -= j * nx / a.mass
    a.vy -= j * ny / a.mass
    a.spin -= j * ra_cross / a.inertia
    b.vx += j * nx / b.mass
    b.vy += j * ny / b.mass
    b.spin += j * rb_cross / b.inertia

    # растаскиваем, чтобы клетки не залипали друг в друге
    total = a.mass + b.mass
    push = overlap * 0.8
    a.x -= nx * push * (b.mass / total)
    a.y -= ny * push * (b.mass / total)
    b.x += nx * push * (a.mass / total)
    b.y += ny * push * (a.mass / total)

    return _damage(a, b, coord_a, coord_b, nx, ny, vax, vay, vbx, vby)


def _find_contact(
    a: Creature, b: Creature
) -> tuple[Coord, Coord, float, float, float] | None:
    """Ищет самую глубокую пару пересекающихся клеток."""
    reach = config.CELL_RADIUS * 2.0
    best: tuple[Coord, Coord, float, float, float] | None = None
    best_overlap = 0.0

    a_cells = [(c, *a.cell_world_pos(c)) for c in a.alive_cells]
    b_cells = [(c, *b.cell_world_pos(c)) for c in b.alive_cells]

    for ca, ax, ay in a_cells:
        for cb, bx, by in b_cells:
            dx, dy = bx - ax, by - ay
            dist = math.hypot(dx, dy)
            if dist >= reach:
                continue
            overlap = reach - dist
            if overlap > best_overlap:
                if dist < 1e-6:
                    nx, ny = 1.0, 0.0
                else:
                    nx, ny = dx / dist, dy / dist
                best = (ca, cb, nx, ny, overlap)
                best_overlap = overlap
    return best


def _damage(
    a: Creature,
    b: Creature,
    coord_a: Coord,
    coord_b: Coord,
    nx: float,
    ny: float,
    vax: float,
    vay: float,
    vbx: float,
    vby: float,
) -> list[Hit]:
    """Кто разогнался сильнее — тот и бьёт. Кость бьёт как остриё."""
    impact = abs((vbx - vax) * nx + (vby - vay) * ny)
    if impact < config.DAMAGE_SPEED:
        return []

    attack_a = vax * nx + vay * ny  # насколько A летит в сторону B
    attack_b = -(vbx * nx + vby * ny)  # насколько B летит в сторону A
    attack_a += _ram_bonus(a, coord_a)
    attack_b += _ram_bonus(b, coord_b)

    losers: list[Hit] = []
    if attack_a > attack_b + config.RAM_ADVANTAGE:
        losers.append((b, coord_b))
    elif attack_b > attack_a + config.RAM_ADVANTAGE:
        losers.append((a, coord_a))
    else:  # лоб в лоб — достаётся обоим
        losers.append((a, coord_a))
        losers.append((b, coord_b))

    hits: list[Hit] = []
    for creature, coord in losers:
        if creature.damage_timer > 0.0:
            continue
        # смятое тело гасит удар: что ушло в сжатие, то не выбило клетку
        softened = impact / (1.0 + config.SOFT_ABSORB * creature.squeeze_at(coord))
        if softened < config.DAMAGE_SPEED * _toughness(creature, coord):
            continue  # кость держит жёсткостью, кожа — мягкостью
        hits.append((creature, coord))

    for creature, _ in hits:
        creature.damage_timer = config.DAMAGE_COOLDOWN
    return hits


def _ram_bonus(creature: Creature, coord: Coord) -> float:
    """Костяное остриё пробивает, даже если сближался медленнее."""
    if creature.blueprint.cells[coord].kind == BONE:
        return config.BONE_RAM_BONUS
    return 0.0


def _toughness(creature: Creature, coord: Coord) -> float:
    """Во сколько раз сильнее должен быть удар, чтобы выбить эту клетку."""
    kind = creature.blueprint.cells[coord].kind
    if kind == BONE:
        return config.BONE_TOUGHNESS
    if kind == PHOTOSYNTH:
        return config.PHOTOSYNTH_TOUGHNESS
    return 1.0
