"""Экраны игры и переходы между ними: редактор → бой → гибель → редактор."""

from __future__ import annotations

import pygame

from evolution import config, render
from evolution.creature import Blueprint
from evolution.editor import EditorScene
from evolution.world import World

__all__ = ["EditorScene", "PlayScene", "GameOverScene"]


class PlayScene:
    """Бой: плаваем, таранимся, подбираем клетки."""

    def __init__(self, blueprint: Blueprint) -> None:
        self.blueprint = blueprint
        self.world = World(blueprint)
        self.active_groups: set[int] = set()
        self.font = render.get_font(20)
        self.small_font = render.get_font(16)
        self.death_delay = 0.0
        self.next_scene = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and pygame.K_1 <= event.key <= pygame.K_9:
            self.active_groups.add(event.key - pygame.K_0)
        elif event.type == pygame.KEYUP and pygame.K_1 <= event.key <= pygame.K_9:
            self.active_groups.discard(event.key - pygame.K_0)

    def update(self, dt: float):
        self.world.update(dt, self.active_groups)
        if self.world.player.is_dead:
            self.death_delay += dt
            if self.death_delay > 1.2:
                return GameOverScene(self.blueprint, self.world.kills)
        return None

    def draw(self, surface: pygame.Surface) -> None:
        camera = render.camera_for(self.world)
        render.draw_background(surface, camera)

        for food in self.world.foods:
            render.draw_food(surface, food, camera)
        for enemy in self.world.enemies:
            render.draw_creature(surface, enemy, camera)
        if not self.world.player.is_dead:
            render.draw_creature(
                surface, self.world.player, camera, self.active_groups, self.small_font
            )

        self._draw_hud(surface)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        player = self.world.player
        lines = [
            f"Съедено врагов: {self.world.kills}",
            f"Клетки: {len(player.alive_cells)} / {len(player.blueprint.cells)}",
            "Двигатели: " + (" ".join(str(g) for g in sorted(player.groups())) or "нет"),
        ]
        y = 14
        for line in lines:
            surface.blit(self.font.render(line, True, config.FG_COLOR), (16, y))
            y += 26
        hint = self.small_font.render(
            "Цифры — двигатели, Esc — выход. Разгонись и врежься во врага.",
            True,
            config.BORDER_COLOR,
        )
        surface.blit(hint, (16, config.HEIGHT - 28))


class GameOverScene:
    """Существо погибло — показываем счёт и возвращаем в редактор."""

    def __init__(self, blueprint: Blueprint, kills: int) -> None:
        self.blueprint = blueprint
        self.kills = kills
        self.font = render.get_font(24)
        self.big_font = render.get_font(48, bold=True)
        self.next_scene = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (
            pygame.K_RETURN,
            pygame.K_KP_ENTER,
            pygame.K_SPACE,
        ):
            self.next_scene = EditorScene(self.blueprint, last_score=self.kills)

    def update(self, dt: float):
        scene, self.next_scene = self.next_scene, None
        return scene

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(config.BG_COLOR)
        center_x = config.WIDTH // 2
        title = self.big_font.render("Существо погибло", True, config.ENEMY_SKIN_COLOR)
        surface.blit(title, title.get_rect(center=(center_x, config.HEIGHT // 2 - 60)))

        score = self.font.render(f"Съедено врагов: {self.kills}", True, config.FG_COLOR)
        surface.blit(score, score.get_rect(center=(center_x, config.HEIGHT // 2)))

        hint = self.font.render("Enter — собрать существо заново", True, config.BORDER_COLOR)
        surface.blit(hint, hint.get_rect(center=(center_x, config.HEIGHT // 2 + 50)))
