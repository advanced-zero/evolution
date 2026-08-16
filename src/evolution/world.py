"""Мир: игрок, враги, плавающие клетки-еда."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from evolution import ai, config, physics
from evolution.creature import ROOT, SKIN, Blueprint, Creature, cell_color, food_energy

if TYPE_CHECKING:
    from evolution.cheats import Cheats


@dataclass
class Food:
    """Отбитая клетка, которая плавает в воде и кормит того, кто её подберёт.

    Обломок выглядит ровно так, как выглядела клетка до отрыва, и по инерции
    продолжает крутиться. Чем дороже была клетка, тем он сытнее.
    """

    x: float
    y: float
    vx: float
    vy: float
    color: tuple[int, int, int] = config.FOOD_COLOR
    angle: float = 0.0
    spin: float = 0.0
    kind: str = SKIN
    direction: int = 0
    life: float = config.FOOD_LIFETIME
    energy: float = config.FOOD_ENERGY[SKIN]

    def step(self, dt: float, decay: float = 1.0) -> None:
        """`decay` — во сколько раз быстрее обломок тает: его топят переработчики."""
        damping = math.exp(-config.FOOD_DRAG * dt)
        self.vx *= damping
        self.vy *= damping
        self.spin *= math.exp(-config.ANGULAR_DRAG * dt)
        self.x = min(max(self.x + self.vx * dt, 0.0), config.WORLD_WIDTH)
        self.y = min(max(self.y + self.vy * dt, 0.0), config.WORLD_HEIGHT)
        self.angle += self.spin * dt
        self.life -= dt * decay


class World:
    def __init__(self, blueprint: Blueprint, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.player = Creature(
            blueprint=blueprint.copy(),
            x=config.WORLD_WIDTH / 2.0,
            y=config.WORLD_HEIGHT / 2.0,
            is_player=True,
            rng=self.rng,
        )
        self.enemies: list[Creature] = []
        self.brains: dict[int, ai.EnemyBrain] = {}
        self.foods: list[Food] = []
        self.kills = 0
        self.time = 0.0
        for _ in range(config.ENEMY_COUNT):
            self.spawn_enemy()

    # --- население мира ---

    def spawn_enemy(self) -> None:
        points = self.rng.randint(config.ENEMY_MIN_POINTS, config.ENEMY_MAX_POINTS)
        blueprint = ai.random_blueprint(points, self.rng)
        for _ in range(60):
            x = self.rng.uniform(100.0, config.WORLD_WIDTH - 100.0)
            y = self.rng.uniform(100.0, config.WORLD_HEIGHT - 100.0)
            if math.hypot(x - self.player.x, y - self.player.y) >= config.ENEMY_SPAWN_MIN_DISTANCE:
                break
        enemy = Creature(
            blueprint=blueprint,
            x=x,
            y=y,
            angle=self.rng.uniform(0.0, 2.0 * math.pi),
            rng=self.rng,
        )
        self.enemies.append(enemy)
        self.brains[id(enemy)] = ai.EnemyBrain(self.rng)

    def creatures(self) -> list[Creature]:
        return ([self.player] if not self.player.is_dead else []) + self.enemies

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
            groups = brain.think(enemy, self.player, self.foods, dt)
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
        self._repair(dt, repairing)
        self._food(dt)
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

    def _repair(self, dt: float, repairing: bool) -> None:
        """Игрок чинится, пока держит кнопку; враги — сами, как только есть чем."""
        if not self.player.is_dead:
            if repairing:
                self.player.repair(dt)
            else:
                self.player.stop_repair()
        for enemy in self.enemies:
            enemy.repair(dt)

    def _collisions(self, cheats: "Cheats | None" = None) -> None:
        invuln = cheats is not None and cheats.invuln
        creatures = self.creatures()
        for i, a in enumerate(creatures):
            for b in creatures[i + 1 :]:
                for creature, coord in physics.collide_pair(a, b):
                    if invuln and creature is self.player:
                        continue
                    self.lose_cell(creature, coord)

    def _food(self, dt: float) -> None:
        """Обломки тают, а переработчики снимают с них энергию.

        Касанием обломок не подобрать: рядом с переработчиком он растворяется в
        `PROCESS_SPEEDUP` раз быстрее (и это складывается), а всю его энергию в
        момент растворения забирает тот, чей переработчик оказался ближе всех.
        """
        creatures = self.creatures()
        # где сейчас все переработчики мира — считаем один раз за кадр
        processors = []
        for creature in creatures:
            creature.processing.clear()
            for coord in creature.processors():
                px, py = creature.cell_world_pos(coord)
                processors.append((creature, coord, px, py))

        alive_food: list[Food] = []
        for food in self.foods:
            melting = 0
            nearest: tuple[float, Creature] | None = None
            for creature, coord, px, py in processors:
                distance = math.hypot(food.x - px, food.y - py)
                if distance <= config.PROCESS_RADIUS:
                    melting += 1
                    creature.processing.add(coord)
                    # работу переработчика оплатим на ближайшем ударе голода
                    creature.work_time[coord] = creature.work_time.get(coord, 0.0) + dt
                if distance <= config.COLLECT_RADIUS and (nearest is None or distance < nearest[0]):
                    nearest = (distance, creature)

            food.step(dt, max(1.0, config.PROCESS_SPEEDUP * melting))
            if food.life > 0.0:
                alive_food.append(food)
            elif nearest is not None:
                nearest[1].eat(food.energy)  # обрезается по баку: сытому впрок не пойдёт
        self.foods = alive_food

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
