"""Столкновения существ и отрыв клеток при таране."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from evolution import config
from evolution.creature import BONE, PHOTOSYNTH, Creature
from evolution.food import Crumb, Food, FoodCell, can_stick, nearest_free_slot
from evolution.hexgrid import Coord

Hit = tuple[Creature, Coord]


@dataclass
class CreatureFoodHit:
    """Итог удара существа об обломок."""

    cells: list[Coord] = field(default_factory=list)
    shatter: bool = False
    split: Coord | None = None


@dataclass
class FoodFoodHit:
    """Итог удара двух обломков."""

    stick: bool = False
    slot: Coord | None = None
    other_hit: Coord | None = None
    shatter_a: bool = False
    shatter_b: bool = False
    split_a: Coord | None = None
    split_b: Coord | None = None


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
    return _kind_toughness(kind)


def _kind_toughness(kind: str) -> float:
    if kind == BONE:
        return config.BONE_TOUGHNESS
    if kind == PHOTOSYNTH:
        return config.PHOTOSYNTH_TOUGHNESS
    return 1.0


def _kind_ram(kind: str) -> float:
    return config.BONE_RAM_BONUS if kind == BONE else 0.0


def _bounce(
    a: object,
    b: object,
    nx: float,
    ny: float,
    overlap: float,
    rax: float,
    ray: float,
    rbx: float,
    rby: float,
    rel_n: float,
) -> None:
    """Общий импульс и расталкивание для двух тел с массой и инерцией."""
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
    total = a.mass + b.mass
    push = overlap * 0.8
    a.x -= nx * push * (b.mass / total)
    a.y -= ny * push * (b.mass / total)
    b.x += nx * push * (a.mass / total)
    b.y += ny * push * (a.mass / total)


def _circle_contact(
    ax: float, ay: float, bx: float, by: float, reach: float
) -> tuple[float, float, float] | None:
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy)
    if dist >= reach:
        return None
    if dist < 1e-6:
        return 1.0, 0.0, reach
    return dx / dist, dy / dist, reach - dist


def collide_creature_food(creature: Creature, food: Food) -> CreatureFoodHit | None:
    """Существо и обломок: отскок, таран или (медленно) ничего липкого — еда к телу не липнет."""
    dx = food.x - creature.x
    dy = food.y - creature.y
    if math.hypot(dx, dy) > creature.radius + food.radius:
        return None
    contact = _find_creature_food_contact(creature, food)
    if contact is None:
        return None
    coord, cell, nx, ny, overlap = contact
    rax, ray = creature.cell_offset(coord)
    rbx, rby = food.cell_offset(cell)
    vax, vay = creature.point_velocity(rax, ray)
    vbx, vby = food.point_velocity(rbx, rby)
    rel_n = (vbx - vax) * nx + (vby - vay) * ny
    if rel_n > 0:
        return None
    _bounce(creature, food, nx, ny, overlap, rax, ray, rbx, rby, rel_n)
    impact = abs(rel_n)
    result = CreatureFoodHit()
    if impact < config.DAMAGE_SPEED:
        return result
    attack_c = vax * nx + vay * ny + _ram_bonus(creature, coord)
    attack_f = -(vbx * nx + vby * ny) + _kind_ram(cell.kind)
    creature_loses = False
    food_loses = False
    if attack_c > attack_f + config.RAM_ADVANTAGE:
        food_loses = True
    elif attack_f > attack_c + config.RAM_ADVANTAGE:
        creature_loses = True
    else:
        creature_loses = True
        food_loses = True
    if creature_loses and creature.damage_timer <= 0.0:
        softened = impact / (1.0 + config.SOFT_ABSORB * creature.squeeze_at(coord))
        if softened >= config.DAMAGE_SPEED * _toughness(creature, coord):
            result.cells.append(coord)
            creature.damage_timer = config.DAMAGE_COOLDOWN
    if food_loses and food.damage_timer <= 0.0:
        if impact >= config.DAMAGE_SPEED * _kind_toughness(cell.kind):
            food.damage_timer = config.DAMAGE_COOLDOWN
            if food.singleton:
                result.shatter = True
            else:
                result.split = cell.coord
    return result


def collide_food_pair(a: Food, b: Food) -> FoodFoodHit | None:
    """Два обломка: медленно могут слипнуться, быстро — таран."""
    dx = b.x - a.x
    dy = b.y - a.y
    if math.hypot(dx, dy) > a.radius + b.radius:
        return None
    contact = _find_food_contact(a, b)
    if contact is None:
        return None
    cell_a, cell_b, nx, ny, overlap = contact
    rax, ray = a.cell_offset(cell_a)
    rbx, rby = b.cell_offset(cell_b)
    vax, vay = a.point_velocity(rax, ray)
    vbx, vby = b.point_velocity(rbx, rby)
    rel_n = (vbx - vax) * nx + (vby - vay) * ny
    if rel_n > 0:
        return None
    impact = abs(rel_n)
    if impact < config.FOOD_STICK_SPEED and can_stick(cell_a, cell_b):
        bxw, byw = b.cell_world_pos(cell_b)
        slot = nearest_free_slot(a, cell_a, bxw, byw)
        if slot is not None:
            return FoodFoodHit(stick=True, slot=slot, other_hit=cell_b.coord)
    _bounce(a, b, nx, ny, overlap, rax, ray, rbx, rby, rel_n)
    result = FoodFoodHit()
    if impact < config.DAMAGE_SPEED:
        return result
    attack_a = vax * nx + vay * ny + _kind_ram(cell_a.kind)
    attack_b = -(vbx * nx + vby * ny) + _kind_ram(cell_b.kind)
    a_loses = False
    b_loses = False
    if attack_a > attack_b + config.RAM_ADVANTAGE:
        b_loses = True
    elif attack_b > attack_a + config.RAM_ADVANTAGE:
        a_loses = True
    else:
        a_loses = True
        b_loses = True
    if a_loses and a.damage_timer <= 0.0 and impact >= config.DAMAGE_SPEED * _kind_toughness(cell_a.kind):
        a.damage_timer = config.DAMAGE_COOLDOWN
        if a.singleton:
            result.shatter_a = True
        else:
            result.split_a = cell_a.coord
    if b_loses and b.damage_timer <= 0.0 and impact >= config.DAMAGE_SPEED * _kind_toughness(cell_b.kind):
        b.damage_timer = config.DAMAGE_COOLDOWN
        if b.singleton:
            result.shatter_b = True
        else:
            result.split_b = cell_b.coord
    return result


def collide_creature_crumb(creature: Creature, crumb: Crumb) -> list[Hit]:
    """Крошка толкается; клетку выбивает только на нереальной скорости."""
    reach = config.CELL_RADIUS + config.FOOD_CRUMB_RADIUS
    hits: list[Hit] = []
    best: tuple[Coord, float, float, float, float, float] | None = None
    best_overlap = 0.0
    for coord in creature.alive_cells:
        ax, ay = creature.cell_world_pos(coord)
        hit = _circle_contact(ax, ay, crumb.x, crumb.y, reach)
        if hit is None:
            continue
        nx, ny, overlap = hit
        if overlap > best_overlap:
            best = (coord, nx, ny, overlap, ax, ay)
            best_overlap = overlap
    if best is None:
        return []
    coord, nx, ny, overlap, ax, ay = best
    rax, ray = creature.cell_offset(coord)
    rbx, rby = crumb.x - crumb.x, crumb.y - crumb.y  # 0, 0: крошка — точка-масса
    vax, vay = creature.point_velocity(rax, ray)
    vbx, vby = crumb.vx, crumb.vy
    rel_n = (vbx - vax) * nx + (vby - vay) * ny
    if rel_n > 0:
        return []
    _bounce(creature, crumb, nx, ny, overlap, rax, ray, 0.0, 0.0, rel_n)
    impact = abs(rel_n)
    if impact < config.FOOD_CRUMB_DAMAGE_SPEED:
        return []
    if creature.damage_timer > 0.0:
        return []
    softened = impact / (1.0 + config.SOFT_ABSORB * creature.squeeze_at(coord))
    if softened < config.FOOD_CRUMB_DAMAGE_SPEED * _toughness(creature, coord):
        return []
    creature.damage_timer = config.DAMAGE_COOLDOWN
    return [(creature, coord)]


def collide_food_crumb(food: Food, crumb: Crumb) -> None:
    """Крошка и целый обломок только отскакивают."""
    reach = config.CELL_RADIUS + config.FOOD_CRUMB_RADIUS
    best: tuple[FoodCell, float, float, float] | None = None
    best_overlap = 0.0
    for cell in food.cells:
        ax, ay = food.cell_world_pos(cell)
        hit = _circle_contact(ax, ay, crumb.x, crumb.y, reach)
        if hit is None:
            continue
        nx, ny, overlap = hit
        if overlap > best_overlap:
            best = (cell, nx, ny, overlap)
            best_overlap = overlap
    if best is None:
        return
    cell, nx, ny, overlap = best
    rax, ray = food.cell_offset(cell)
    vax, vay = food.point_velocity(rax, ray)
    rel_n = (crumb.vx - vax) * nx + (crumb.vy - vay) * ny
    if rel_n > 0:
        return
    _bounce(food, crumb, nx, ny, overlap, rax, ray, 0.0, 0.0, rel_n)


def collide_crumb_pair(a: Crumb, b: Crumb) -> None:
    reach = config.FOOD_CRUMB_RADIUS * 2.0
    hit = _circle_contact(a.x, a.y, b.x, b.y, reach)
    if hit is None:
        return
    nx, ny, overlap = hit
    rel_n = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
    if rel_n > 0:
        return
    _bounce(a, b, nx, ny, overlap, 0.0, 0.0, 0.0, 0.0, rel_n)


def _find_creature_food_contact(
    creature: Creature, food: Food
) -> tuple[Coord, FoodCell, float, float, float] | None:
    reach = config.CELL_RADIUS * 2.0
    best: tuple[Coord, FoodCell, float, float, float] | None = None
    best_overlap = 0.0
    a_cells = [(c, *creature.cell_world_pos(c)) for c in creature.alive_cells]
    for ca, ax, ay in a_cells:
        for cell in food.cells:
            bx, by = food.cell_world_pos(cell)
            hit = _circle_contact(ax, ay, bx, by, reach)
            if hit is None:
                continue
            nx, ny, overlap = hit
            if overlap > best_overlap:
                best = (ca, cell, nx, ny, overlap)
                best_overlap = overlap
    return best


def _find_food_contact(
    a: Food, b: Food
) -> tuple[FoodCell, FoodCell, float, float, float] | None:
    reach = config.CELL_RADIUS * 2.0
    best: tuple[FoodCell, FoodCell, float, float, float] | None = None
    best_overlap = 0.0
    for ca in a.cells:
        ax, ay = a.cell_world_pos(ca)
        for cb in b.cells:
            bx, by = b.cell_world_pos(cb)
            hit = _circle_contact(ax, ay, bx, by, reach)
            if hit is None:
                continue
            nx, ny, overlap = hit
            if overlap > best_overlap:
                best = (ca, cb, nx, ny, overlap)
                best_overlap = overlap
    return best
