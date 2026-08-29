"""Мир: игрок, враги, плавающие клетки-еда."""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from evolution import ai, config, physics
from evolution.creature import ROOT, SKIN, Blueprint, Creature, Species, cell_color, food_energy
from evolution.food import Crumb, Food

if TYPE_CHECKING:
    from evolution.cheats import Cheats

__all__ = ["Crumb", "Food", "World"]


class World:
    def __init__(self, species: Species | Blueprint, seed: int | None = None) -> None:
        if isinstance(species, Blueprint):
            species = Species([species])
        self.species = species.copy()
        self.rng = random.Random(seed)
        self.player = Creature(
            blueprint=self.species.stages[0].copy(),
            species=self.species,
            x=config.WORLD_WIDTH / 2.0,
            y=config.WORLD_HEIGHT / 2.0,
            is_player=True,
            rng=self.rng,
        )
        self.enemies: list[Creature] = []
        self.brains: dict[int, ai.EnemyBrain] = {}
        self.foods: list[Food] = []
        self.crumbs: list[Crumb] = []
        self.kills = 0
        self.time = 0.0
        for _ in range(config.ENEMY_COUNT):
            self.spawn_enemy()

    # --- население мира ---

    def spawn_enemy(self) -> None:
        points = self.rng.randint(config.ENEMY_MIN_POINTS, config.ENEMY_MAX_POINTS)
        species = ai.random_species(points, self.rng)
        for _ in range(60):
            x = self.rng.uniform(100.0, config.WORLD_WIDTH - 100.0)
            y = self.rng.uniform(100.0, config.WORLD_HEIGHT - 100.0)
            if math.hypot(x - self.player.x, y - self.player.y) >= config.ENEMY_SPAWN_MIN_DISTANCE:
                break
        enemy = Creature(
            blueprint=species.stages[0].copy(),
            species=species,
            x=x,
            y=y,
            angle=self.rng.uniform(0.0, 2.0 * math.pi),
            rng=self.rng,
        )
        self.enemies.append(enemy)
        self.brains[id(enemy)] = ai.EnemyBrain(self.rng)

    def creatures(self) -> list[Creature]:
        return ([self.player] if not self.player.is_dead else []) + self.enemies

    def bait_points(self) -> list[tuple[float, float]]:
        """Точки еды для глаза: клетки обломков и крошки."""
        points: list[tuple[float, float]] = []
        for food in self.foods:
            for cell in food.cells:
                points.append(food.cell_world_pos(cell))
        points.extend((crumb.x, crumb.y) for crumb in self.crumbs)
        return points

    def lose_cell(self, creature: Creature, coord: tuple[int, int]) -> None:
        """Выбивает клетку и роняет в воду её саму и всё, что через неё держалось."""
        # снимок делаем до удаления: потом у оторванных клеток уже нет ни места,
        # ни скорости — центр тяжести существа сместился
        snapshot = {c: (*creature.cell_world_pos(c), *creature.cell_velocity(c)) for c in creature.alive_cells}
        self.drop_food(creature, creature.remove_cell(coord), snapshot)

    def drop_food(
        self,
        creature: Creature,
        coords: list[tuple[int, int]],
        snapshot: dict[tuple[int, int], tuple[float, float, float, float]] | None = None,
    ) -> None:
        for coord in coords:
            if snapshot is not None and coord in snapshot:
                x, y, cvx, cvy = snapshot[coord]
            else:
                x, y = creature.cell_world_pos(coord)
                # обломок улетает со скоростью того места, где он был: оторванный
                # кончик хлещущего хвоста летит быстрее самого существа
                cvx, cvy = creature.cell_velocity(coord)
            spec = creature.blueprint.cells[coord]
            self.foods.append(
                Food(
                    x=x,
                    y=y,
                    vx=cvx * 0.4 + self.rng.uniform(-90.0, 90.0),
                    vy=cvy * 0.4 + self.rng.uniform(-90.0, 90.0),
                    color=cell_color(coord, spec, creature.is_player),
                    angle=creature.angle,
                    spin=creature.spin + self.rng.uniform(-2.5, 2.5),
                    kind=spec.kind,
                    direction=spec.direction,
                    energy=food_energy(spec.kind, coord == ROOT),
                    is_brain=coord == ROOT,
                )
            )

    # --- главный шаг ---

    def update(
        self,
        dt: float,
        player_groups: set[int],
        repairing: bool = False,
        cheats: "Cheats | None" = None,
    ) -> None:
        # cheats: см. evolution.cheats.Cheats — необязательный крючок для читов,
        # чтобы их можно было убрать целиком, удалив cheats.py и эти строки
        self.time += dt

        if cheats is not None and cheats.energy and not self.player.is_dead:
            self.player.energy = self.player.max_energy

        if not self.player.is_dead:
            self.player.apply_thrust(player_groups, dt)
            self.player.apply_muscles(player_groups, dt)
        for enemy in self.enemies:
            brain = self.brains[id(enemy)]
            groups = brain.think(enemy, self.player, self.foods, dt, self.crumbs)
            enemy.apply_thrust(groups, dt)
            enemy.apply_muscles(groups, dt)

        for creature in self.creatures():
            creature.step(dt)
            # клетку могло растащить с соседями или смять в лепёшку — тогда она
            # отваливается сама, без всякого тарана
            for coord in creature.torn:
                if coord in creature.alive_cells:
                    self.lose_cell(creature, coord)

        self._collisions(cheats)
        self._hunger()
        self._food(dt)
        self._evolve()
        self._repair(dt, repairing)
        self._evolve()  # за этот кадр могли дорасти — сразу следующий этап
        self._cleanup()

    def _hunger(self) -> None:
        """Удар голода: у кого не хватило энергии, тот худеет с краёв."""
        for creature in self.creatures():
            if not creature.hunger_due:
                continue
            # снимок до объедания — как и при таране, иначе клеткам неоткуда взяться
            snapshot = {
                c: (*creature.cell_world_pos(c), *creature.cell_velocity(c))
                for c in creature.alive_cells
            }
            self.drop_food(creature, creature.starve(), snapshot)

    def _evolve(self) -> None:
        """У кого хватило энергии на следующий этап — сбрасывает лишнее и растёт.

        Пока плата нулевая и тело уже совпадает, этапы скипаются в том же кадре.
        """
        for creature in self.creatures():
            while True:
                cost = creature.next_evolve_cost()
                if cost is None or creature.energy + 1e-6 < cost:
                    break
                snapshot = {
                    c: (*creature.cell_world_pos(c), *creature.cell_velocity(c))
                    for c in creature.alive_cells
                }
                lost = creature.shed_for_next()
                self.drop_food(creature, lost, snapshot)
                creature.start_growing_next()
                if creature.evolving:
                    break

    def _repair(self, dt: float, repairing: bool) -> None:
        """Игрок чинится по R; во время линьки рост идёт сам. Враги чинятся сами."""
        if not self.player.is_dead:
            if self.player.evolving or repairing:
                self.player.repair(dt)
            else:
                self.player.stop_repair()
        for enemy in self.enemies:
            enemy.repair(dt)

    def _shatter(self, food: Food) -> None:
        self.crumbs.extend(food.shatter())

    def _collisions(self, cheats: "Cheats | None" = None) -> None:
        invuln = cheats is not None and cheats.invuln
        creatures = self.creatures()
        for i, a in enumerate(creatures):
            for b in creatures[i + 1 :]:
                for creature, coord in physics.collide_pair(a, b):
                    if invuln and creature is self.player:
                        continue
                    self.lose_cell(creature, coord)

        gone_food: set[int] = set()
        extra_food: list[Food] = []
        for creature in creatures:
            for food in self.foods:
                if id(food) in gone_food or not food.cells:
                    continue
                hit = physics.collide_creature_food(creature, food)
                if hit is None:
                    continue
                for coord in hit.cells:
                    if invuln and creature is self.player:
                        continue
                    self.lose_cell(creature, coord)
                if hit.shatter:
                    self._shatter(food)
                    gone_food.add(id(food))
                elif hit.split is not None:
                    piece = food.split_cell(hit.split)
                    if piece is not None:
                        extra_food.append(piece)

        foods = [food for food in self.foods if id(food) not in gone_food] + extra_food
        extra_food = []
        for i, a in enumerate(foods):
            if id(a) in gone_food or not a.cells:
                continue
            for b in foods[i + 1 :]:
                if id(b) in gone_food or not b.cells:
                    continue
                hit = physics.collide_food_pair(a, b)
                if hit is None:
                    continue
                if hit.stick and hit.slot is not None and hit.other_hit is not None:
                    if a.absorb(b, hit.slot, hit.other_hit):
                        gone_food.add(id(b))
                    else:
                        dx, dy = b.x - a.x, b.y - a.y
                        dist = math.hypot(dx, dy) or 1.0
                        b.x += dx / dist * 4.0
                        b.y += dy / dist * 4.0
                    continue
                if hit.shatter_a:
                    self._shatter(a)
                    gone_food.add(id(a))
                elif hit.split_a is not None:
                    piece = a.split_cell(hit.split_a)
                    if piece is not None:
                        extra_food.append(piece)
                if hit.shatter_b:
                    self._shatter(b)
                    gone_food.add(id(b))
                elif hit.split_b is not None:
                    piece = b.split_cell(hit.split_b)
                    if piece is not None:
                        extra_food.append(piece)

        self.foods = [food for food in foods if id(food) not in gone_food] + extra_food

        for creature in self.creatures():
            for crumb in self.crumbs:
                for who, coord in physics.collide_creature_crumb(creature, crumb):
                    if invuln and who is self.player:
                        continue
                    self.lose_cell(who, coord)

        for food in self.foods:
            for crumb in self.crumbs:
                physics.collide_food_crumb(food, crumb)
        for i, a in enumerate(self.crumbs):
            for b in self.crumbs[i + 1 :]:
                physics.collide_crumb_pair(a, b)

    def _food(self, dt: float) -> None:
        """Обломки тают, крошки подбирает кожа, переработчики снимают энергию.

        Целую клетку касанием не взять: рядом с переработчиком она растворяется в
        `PROCESS_SPEEDUP` раз быстрее (и это складывается), а энергию в момент
        растворения забирает тот, чей переработчик ближе всех.
        """
        creatures = self.creatures()
        processors = []
        for creature in creatures:
            creature.processing.clear()
            for coord in creature.processors():
                px, py = creature.cell_world_pos(coord)
                processors.append((creature, coord, px, py))

        skins: list[tuple[Creature, float, float]] = []
        for creature in creatures:
            for coord in creature.alive_cells:
                if creature.kind_of(coord) != SKIN:
                    continue
                sx, sy = creature.cell_world_pos(coord)
                skins.append((creature, sx, sy))

        moved: list[Food] = []
        for food in self.foods:
            moved.extend(food.move(dt))
        self.foods.extend(moved)

        alive_food: list[Food] = []
        born: list[Food] = []
        for food in self.foods:
            if not food.cells:
                continue
            kept = []
            for cell in food.cells:
                melting = 0
                nearest: tuple[float, Creature] | None = None
                cx, cy = food.cell_world_pos(cell)
                for creature, coord, px, py in processors:
                    distance = math.hypot(cx - px, cy - py)
                    if distance <= config.PROCESS_RADIUS:
                        melting += 1
                        creature.processing.add(coord)
                        creature.work_time[coord] = creature.work_time.get(coord, 0.0) + dt
                    if distance <= config.COLLECT_RADIUS and (
                        nearest is None or distance < nearest[0]
                    ):
                        nearest = (distance, creature)
                # одиночка без переработчиков тает как раньше: decay 1
                cell.life -= dt * max(1.0, config.PROCESS_SPEEDUP * melting)
                if cell.life > 0.0:
                    kept.append(cell)
                elif nearest is not None:
                    nearest[1].eat(cell.energy)
            food.cells = kept
            if not food.cells:
                continue
            food._recompute(keep_position=True)
            born.extend(food.split_disconnected())
            alive_food.append(food)
        self.foods = alive_food + born

        alive_crumbs: list[Crumb] = []
        for crumb in self.crumbs:
            melting = 0
            nearest: tuple[float, Creature] | None = None
            picked = False
            for creature, sx, sy in skins:
                if math.hypot(crumb.x - sx, crumb.y - sy) <= config.CELL_RADIUS + config.FOOD_CRUMB_RADIUS:
                    if creature.eat(crumb.energy):
                        picked = True
                        break
            if picked:
                continue
            for creature, coord, px, py in processors:
                distance = math.hypot(crumb.x - px, crumb.y - py)
                if distance <= config.PROCESS_RADIUS:
                    melting += 1
                    creature.processing.add(coord)
                    creature.work_time[coord] = creature.work_time.get(coord, 0.0) + dt
                if distance <= config.COLLECT_RADIUS and (nearest is None or distance < nearest[0]):
                    nearest = (distance, creature)
            crumb.step(dt, max(1.0, config.PROCESS_SPEEDUP * melting))
            if crumb.life > 0.0:
                alive_crumbs.append(crumb)
            elif nearest is not None:
                nearest[1].eat(crumb.energy)
        self.crumbs = alive_crumbs

    def _cleanup(self) -> None:
        survivors: list[Creature] = []
        for enemy in self.enemies:
            if enemy.is_dead:
                self.drop_food(enemy, list(enemy.alive_cells))
                self.brains.pop(id(enemy), None)
                self.kills += 1
            else:
                survivors.append(enemy)
        self.enemies = survivors
        while len(self.enemies) < config.ENEMY_COUNT:
            self.spawn_enemy()
