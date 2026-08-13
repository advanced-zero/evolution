"""Мир: игрок, враги, плавающие клетки-еда."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from evolution import ai, config, physics
from evolution.creature import Blueprint, Creature


@dataclass
class Food:
    """Отбитая клетка, которая плавает в воде и лечит того, кто её подберёт."""

    x: float
    y: float
    vx: float
    vy: float
    life: float = config.FOOD_LIFETIME

    def step(self, dt: float) -> None:
        damping = math.exp(-config.FOOD_DRAG * dt)
        self.vx *= damping
        self.vy *= damping
        self.x = min(max(self.x + self.vx * dt, 0.0), config.WORLD_WIDTH)
        self.y = min(max(self.y + self.vy * dt, 0.0), config.WORLD_HEIGHT)
        self.life -= dt


class World:
    def __init__(self, blueprint: Blueprint, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.player = Creature(
            blueprint=blueprint.copy(),
            x=config.WORLD_WIDTH / 2.0,
            y=config.WORLD_HEIGHT / 2.0,
            is_player=True,
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
        cells = self.rng.randint(config.ENEMY_MIN_CELLS, config.ENEMY_MAX_CELLS)
        blueprint = ai.random_blueprint(cells, self.rng)
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
        )
        self.enemies.append(enemy)
        self.brains[id(enemy)] = ai.EnemyBrain(self.rng)

    def creatures(self) -> list[Creature]:
        return ([self.player] if not self.player.is_dead else []) + self.enemies

    def drop_food(self, creature: Creature, coords: list[tuple[int, int]]) -> None:
        for coord in coords:
            x, y = creature.cell_world_pos(coord)
            self.foods.append(
                Food(
                    x=x,
                    y=y,
                    vx=creature.vx * 0.4 + self.rng.uniform(-90.0, 90.0),
                    vy=creature.vy * 0.4 + self.rng.uniform(-90.0, 90.0),
                )
            )

    # --- главный шаг ---

    def update(self, dt: float, player_groups: set[int]) -> None:
        self.time += dt

        if not self.player.is_dead:
            self.player.apply_thrust(player_groups, dt)
        for enemy in self.enemies:
            brain = self.brains[id(enemy)]
            enemy.apply_thrust(brain.think(enemy, self.player, dt), dt)

        for creature in self.creatures():
            creature.step(dt)

        self._collisions()
        self._food(dt)
        self._cleanup()

    def _collisions(self) -> None:
        creatures = self.creatures()
        for i, a in enumerate(creatures):
            for b in creatures[i + 1 :]:
                for creature, coord in physics.collide_pair(a, b):
                    lost = creature.remove_cell(coord)
                    self.drop_food(creature, lost)

    def _food(self, dt: float) -> None:
        alive_food: list[Food] = []
        creatures = self.creatures()
        for food in self.foods:
            food.step(dt)
            if food.life <= 0.0:
                continue
            eaten = False
            for creature in creatures:
                if creature.lost_count <= 0:
                    continue
                if math.hypot(food.x - creature.x, food.y - creature.y) > creature.radius + config.FOOD_PICKUP_RADIUS:
                    continue
                for coord in creature.alive_cells:
                    cx, cy = creature.cell_world_pos(coord)
                    if math.hypot(food.x - cx, food.y - cy) <= config.FOOD_PICKUP_RADIUS:
                        if creature.heal(1):
                            eaten = True
                        break
                if eaten:
                    break
            if not eaten:
                alive_food.append(food)
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
