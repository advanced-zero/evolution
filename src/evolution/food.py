"""Плавающие обломки: целые клетки, мягкие кучи и крошки после удара."""

from __future__ import annotations

import math
from dataclasses import dataclass

from evolution import config, hexgrid
from evolution.creature import (
    BONE,
    EYE,
    PHOTOSYNTH,
    SKIN,
    cell_mass,
    food_energy,
    rotate,
)
from evolution.hexgrid import Coord


def stickiness(kind: str, is_brain: bool) -> float:
    """Насколько охотно этот вид липнет к другому обломку."""
    if kind == BONE:
        return config.FOOD_STICK_BONE
    if kind == PHOTOSYNTH:
        return config.FOOD_STICK_PHOTOSYNTH
    if is_brain:
        return config.FOOD_STICK_BRAIN
    if kind == SKIN:
        return config.FOOD_STICK_SKIN
    return config.FOOD_STICK_WEAK


def can_stick(a: FoodCell, b: FoodCell) -> bool:
    return stickiness(a.kind, a.is_brain) * stickiness(b.kind, b.is_brain) >= config.FOOD_STICK_MIN


@dataclass
class FoodCell:
    """Одна клетка внутри обломка или кучи."""

    coord: Coord
    kind: str = SKIN
    direction: int = 0
    energy: float = 5.0
    color: tuple[int, int, int] = config.FOOD_COLOR
    is_brain: bool = False
    ox: float = 0.0
    oy: float = 0.0
    life: float = config.FOOD_LIFETIME


@dataclass
class Crumb:
    """Осколок одиночного обломка: лёгкий, подбирает только кожа."""

    x: float
    y: float
    vx: float
    vy: float
    energy: float
    color: tuple[int, int, int] = config.FOOD_COLOR
    angle: float = 0.0
    spin: float = 0.0
    life: float = config.FOOD_LIFETIME
    damage_timer: float = 0.0

    @property
    def mass(self) -> float:
        return config.FOOD_CRUMB_MASS

    @property
    def inertia(self) -> float:
        return max(self.mass * config.FOOD_CRUMB_SIZE**2 * 0.5, 0.05)

    @property
    def radius(self) -> float:
        return config.FOOD_CRUMB_RADIUS

    def step(self, dt: float, decay: float = 1.0) -> None:
        damping = math.exp(-config.FOOD_DRAG * dt)
        self.vx *= damping
        self.vy *= damping
        self.spin *= math.exp(-config.ANGULAR_DRAG * dt)
        self.x = min(max(self.x + self.vx * dt, 0.0), config.WORLD_WIDTH)
        self.y = min(max(self.y + self.vy * dt, 0.0), config.WORLD_HEIGHT)
        self.angle += self.spin * dt
        self.life -= dt * decay
        self.damage_timer = max(0.0, self.damage_timer - dt)


class Food:
    """Отбитая клетка или слипшаяся куча. Крошится только одиночка."""

    def __init__(
        self,
        x: float,
        y: float,
        vx: float,
        vy: float,
        color: tuple[int, int, int] = config.FOOD_COLOR,
        angle: float = 0.0,
        spin: float = 0.0,
        kind: str = SKIN,
        direction: int = 0,
        life: float = config.FOOD_LIFETIME,
        energy: float | None = None,
        is_brain: bool = False,
        cells: list[FoodCell] | None = None,
    ) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.angle = angle
        self.spin = spin
        self.damage_timer = 0.0
        if cells is not None:
            self.cells = cells
        else:
            if energy is None:
                energy = food_energy(kind, is_brain)
            self.cells = [
                FoodCell(
                    coord=(0, 0),
                    kind=kind,
                    direction=direction,
                    energy=energy,
                    color=color,
                    is_brain=is_brain,
                    life=life,
                )
            ]
        self.com_x = 0.0
        self.com_y = 0.0
        self.mass = config.CELL_MASS
        self.inertia = 1.0
        self.radius = config.CELL_RADIUS
        self._recompute(keep_position=False)

    @property
    def kind(self) -> str:
        return self.cells[0].kind if self.cells else SKIN

    @property
    def direction(self) -> int:
        return self.cells[0].direction if self.cells else 0

    @property
    def color(self) -> tuple[int, int, int]:
        return self.cells[0].color if self.cells else config.FOOD_COLOR

    @property
    def is_brain(self) -> bool:
        return any(cell.is_brain for cell in self.cells)

    @property
    def energy(self) -> float:
        return sum(cell.energy for cell in self.cells)

    @property
    def life(self) -> float:
        if not self.cells:
            return 0.0
        return min(cell.life for cell in self.cells)

    @life.setter
    def life(self, value: float) -> None:
        for cell in self.cells:
            cell.life = value

    @property
    def singleton(self) -> bool:
        return len(self.cells) == 1

    def occupied(self) -> set[Coord]:
        return {cell.coord for cell in self.cells}

    def rest_pos(self, coord: Coord) -> tuple[float, float]:
        px, py = hexgrid.hex_to_pixel(coord, config.HEX_SIZE)
        return px - self.com_x, py - self.com_y

    def local_pos(self, cell: FoodCell) -> tuple[float, float]:
        px, py = self.rest_pos(cell.coord)
        return px + cell.ox, py + cell.oy

    def cell_world_pos(self, cell: FoodCell) -> tuple[float, float]:
        lx, ly = self.local_pos(cell)
        rx, ry = rotate(lx, ly, self.angle)
        return self.x + rx, self.y + ry

    def cell_offset(self, cell: FoodCell) -> tuple[float, float]:
        lx, ly = self.local_pos(cell)
        return rotate(lx, ly, self.angle)

    def point_velocity(self, ox: float, oy: float) -> tuple[float, float]:
        return self.vx - self.spin * oy, self.vy + self.spin * ox

    def _recompute(self, keep_position: bool = True) -> None:
        if not self.cells:
            self.mass = config.CELL_MASS
            self.inertia = 1.0
            self.radius = config.CELL_RADIUS
            self.com_x = 0.0
            self.com_y = 0.0
            return
        weighted = [
            (*hexgrid.hex_to_pixel(cell.coord, config.HEX_SIZE), cell_mass(cell.kind))
            for cell in self.cells
        ]
        total = sum(m for _, _, m in weighted)
        new_com_x = sum(px * m for px, _, m in weighted) / total
        new_com_y = sum(py * m for _, py, m in weighted) / total
        if keep_position:
            dx, dy = rotate(new_com_x - self.com_x, new_com_y - self.com_y, self.angle)
            self.x += dx
            self.y += dy
        self.com_x, self.com_y = new_com_x, new_com_y
        self.mass = total
        inertia = 0.0
        radius = 0.0
        for px, py, m in weighted:
            dx, dy = px - new_com_x, py - new_com_y
            inertia += m * (dx * dx + dy * dy) + m * config.HEX_SIZE**2 * 0.5
            radius = max(radius, math.hypot(dx, dy))
        self.inertia = max(inertia, 1.0)
        self.radius = radius + config.CELL_RADIUS + config.HEX_SIZE

    def move(self, dt: float) -> list[Food]:
        """Плывёт в воде. Кучи могут порваться — куски возвращаются отдельно."""
        n = max(1, len(self.cells))
        damping = math.exp(-config.FOOD_DRAG * (1.0 + 0.35 * (n - 1)) * dt)
        self.vx *= damping
        self.vy *= damping
        self.spin *= math.exp(-config.ANGULAR_DRAG * dt)
        self.x = min(max(self.x + self.vx * dt, 0.0), config.WORLD_WIDTH)
        self.y = min(max(self.y + self.vy * dt, 0.0), config.WORLD_HEIGHT)
        self.angle += self.spin * dt
        self.damage_timer = max(0.0, self.damage_timer - dt)
        if len(self.cells) > 1:
            return self.soft_step()
        return []

    def step(self, dt: float, decay: float = 1.0) -> None:
        """Движение и общее таяние — так вызывают тесты одиночки."""
        self.move(dt)
        for cell in self.cells:
            cell.life -= dt * decay

    def soft_step(self) -> list[Food]:
        """Подтягивает соседей и отрывает то, что растянуло слишком сильно."""
        torn: list[Food] = []
        by_coord = {cell.coord: cell for cell in self.cells}
        rest = config.HEX_STEP
        for _ in range(config.SOFT_ITERATIONS):
            for cell in self.cells:
                for ncoord in hexgrid.neighbors(cell.coord):
                    other = by_coord.get(ncoord)
                    if other is None or id(other) <= id(cell):
                        continue
                    ax, ay = self.local_pos(cell)
                    bx, by = self.local_pos(other)
                    dx, dy = bx - ax, by - ay
                    dist = math.hypot(dx, dy)
                    if dist < 1e-6:
                        continue
                    stick = stickiness(cell.kind, cell.is_brain) * stickiness(
                        other.kind, other.is_brain
                    )
                    stiff = config.SOFT_LINK_SKIN * (0.35 + 0.65 * min(1.0, stick))
                    error = dist - rest
                    if error < 0.0:
                        stiff = config.SOFT_SQUEEZE_STIFF
                    corr = error * stiff * 0.5
                    nx, ny = dx / dist, dy / dist
                    cell.ox += nx * corr
                    cell.oy += ny * corr
                    other.ox -= nx * corr
                    other.oy -= ny * corr

        leftover = list(self.cells)
        by_coord = {cell.coord: cell for cell in leftover}
        for cell in list(leftover):
            if cell not in leftover:
                continue
            for ncoord in hexgrid.neighbors(cell.coord):
                other = by_coord.get(ncoord)
                if other is None or id(other) <= id(cell):
                    continue
                ax, ay = self.local_pos(cell)
                bx, by = self.local_pos(other)
                dist = math.hypot(bx - ax, by - ay)
                stick = stickiness(cell.kind, cell.is_brain) * stickiness(
                    other.kind, other.is_brain
                )
                limit = config.SOFT_TEAR_STRETCH * (0.7 + 0.4 * min(1.0, stick))
                if dist > rest * limit:
                    piece = self._detach({other.coord})
                    if piece is not None:
                        torn.append(piece)
                    leftover = list(self.cells)
                    by_coord = {c.coord: c for c in leftover}
                    break
        return torn

    def shatter(self) -> list[Crumb]:
        """Одиночный обломок рассыпается в крошки с той же суммой энергии."""
        total = self.energy
        rich = self.cells[0].is_brain or self.cells[0].kind in (BONE, EYE)
        n = config.FOOD_CRUMB_COUNT_RICH if rich else config.FOOD_CRUMB_COUNT
        share = total / n
        crumbs: list[Crumb] = []
        color = self.color
        life = self.life
        for i in range(n):
            ang = self.angle + i * (2.0 * math.pi / n)
            c, s = math.cos(ang), math.sin(ang)
            crumbs.append(
                Crumb(
                    x=self.x + c * config.HEX_SIZE * 0.4,
                    y=self.y + s * config.HEX_SIZE * 0.4,
                    vx=self.vx + c * config.FOOD_SHATTER_SPEED,
                    vy=self.vy + s * config.FOOD_SHATTER_SPEED,
                    energy=share,
                    color=color,
                    angle=self.angle,
                    spin=self.spin + (i - 1) * 2.0,
                    life=life,
                )
            )
        return crumbs

    def absorb(self, other: Food, slot: Coord, other_hit: Coord) -> bool:
        """Приклеивает другой обломок, сажая клетку касания в свободный гекс."""
        oq, orr = other_hit
        sq, sr = slot
        dq, dr = sq - oq, sr - orr
        taken = self.occupied()
        moved: list[FoodCell] = []
        for cell in other.cells:
            coord = (cell.coord[0] + dq, cell.coord[1] + dr)
            if coord in taken:
                return False
            taken.add(coord)
            moved.append(
                FoodCell(
                    coord=coord,
                    kind=cell.kind,
                    direction=cell.direction,
                    energy=cell.energy,
                    color=cell.color,
                    is_brain=cell.is_brain,
                    life=cell.life,
                )
            )
        total = self.mass + other.mass
        self.vx = (self.vx * self.mass + other.vx * other.mass) / total
        self.vy = (self.vy * self.mass + other.vy * other.mass) / total
        self.spin = (self.spin * self.mass + other.spin * other.mass) / total
        self.cells.extend(moved)
        self._recompute(keep_position=True)
        return True

    def _detach(self, coords: set[Coord]) -> Food | None:
        """Откалывает клетки отдельным обломком; пустую кучу не оставляет."""
        if not coords or coords >= self.occupied():
            return None
        staying = [cell for cell in self.cells if cell.coord not in coords]
        leaving = [cell for cell in self.cells if cell.coord in coords]
        if not staying or not leaving:
            return None
        world: list[tuple[FoodCell, float, float, float, float]] = []
        for cell in leaving:
            x, y = self.cell_world_pos(cell)
            ox, oy = self.cell_offset(cell)
            vx, vy = self.point_velocity(ox, oy)
            world.append((cell, x, y, vx, vy))
        self.cells = staying
        self._recompute(keep_position=True)
        piece = Food(
            x=sum(p[1] for p in world) / len(world),
            y=sum(p[2] for p in world) / len(world),
            vx=sum(p[3] for p in world) / len(world),
            vy=sum(p[4] for p in world) / len(world),
            angle=self.angle,
            spin=self.spin,
            cells=[
                FoodCell(
                    coord=cell.coord,
                    kind=cell.kind,
                    direction=cell.direction,
                    energy=cell.energy,
                    color=cell.color,
                    is_brain=cell.is_brain,
                    life=cell.life,
                )
                for cell, *_ in world
            ],
        )
        piece._normalize_coords()
        return piece

    def split_cell(self, coord: Coord) -> Food | None:
        """Откалывает одну клетку целиком — удар по куче не крошит."""
        return self._detach({coord})

    def split_disconnected(self) -> list[Food]:
        """Если куча развалилась на части — каждая часть отдельный обломок."""
        remaining = {cell.coord for cell in self.cells}
        if len(remaining) <= 1:
            return []
        components: list[set[Coord]] = []
        seen: set[Coord] = set()
        for start in remaining:
            if start in seen:
                continue
            pile = {start}
            queue = [start]
            seen.add(start)
            while queue:
                current = queue.pop()
                for n in hexgrid.neighbors(current):
                    if n in remaining and n not in seen:
                        seen.add(n)
                        pile.add(n)
                        queue.append(n)
            components.append(pile)
        if len(components) <= 1:
            return []
        extras: list[Food] = []
        for pile in components[1:]:
            piece = self._detach(pile)
            if piece is not None:
                extras.append(piece)
        return extras

    def _normalize_coords(self) -> None:
        """Сдвигает гексы так, чтобы какая-то клетка была ближе к (0, 0)."""
        if not self.cells:
            return
        best = min(self.cells, key=lambda c: hexgrid.distance((0, 0), c.coord))
        dq, dr = best.coord
        if dq == 0 and dr == 0:
            self._recompute(keep_position=False)
            return
        for cell in self.cells:
            cell.coord = (cell.coord[0] - dq, cell.coord[1] - dr)
        self._recompute(keep_position=False)


def nearest_free_slot(food: Food, hit: FoodCell, world_x: float, world_y: float) -> Coord | None:
    """Свободный сосед клетки касания, ближайший к точке в мире."""
    taken = food.occupied()
    best: Coord | None = None
    best_d = 1e9
    for slot in hexgrid.neighbors(hit.coord):
        if slot in taken:
            continue
        rest = food.rest_pos(slot)
        rx, ry = rotate(rest[0], rest[1], food.angle)
        sx, sy = food.x + rx, food.y + ry
        d = (sx - world_x) ** 2 + (sy - world_y) ** 2
        if d < best_d:
            best, best_d = slot, d
    return best
