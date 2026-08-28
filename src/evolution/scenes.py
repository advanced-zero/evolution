"""Экраны игры и переходы между ними: редактор → бой → гибель → редактор."""

from __future__ import annotations

import pygame

from evolution import config, render
from evolution.cheats import Cheats
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
        self.repairing = False
        self.cheats = Cheats()
        self.font = render.get_font(20)
        self.small_font = render.get_font(16)
        self.death_delay = 0.0
        self.next_scene = None
        self._world_surface: pygame.Surface | None = None
        self._world_surface_size: tuple[int, int] | None = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and pygame.K_1 <= event.key <= pygame.K_9:
            self.active_groups.add(event.key - pygame.K_0)
        elif event.type == pygame.KEYUP and pygame.K_1 <= event.key <= pygame.K_9:
            self.active_groups.discard(event.key - pygame.K_0)
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
            self.repairing = True
        elif event.type == pygame.KEYUP and event.key == pygame.K_r:
            self.repairing = False
        else:
            self.cheats.handle_event(event, self.world)

    def update(self, dt: float):
        self.world.update(dt, self.active_groups, self.repairing, self.cheats)
        if self.world.player.is_dead:
            self.death_delay += dt
            if self.death_delay > 1.2:
                return GameOverScene(self.blueprint, self.world.kills)
        return None

    def _camera_zoom(self) -> float:
        """Во сколько раз растянуть вид: меньше существо — сильнее приближение."""
        diameter = self.world.player.visual_extent() * 2.0 * config.CAMERA_FIT_MARGIN
        zoom = config.HEIGHT / diameter
        zoom = min(config.CAMERA_ZOOM_MAX, max(config.CAMERA_ZOOM_MIN, zoom))
        # живые зрительные клетки отдаляют камеру — виднее становится море вокруг
        eye_bonus = 1.0 + config.CAMERA_EYE_ZOOM_BONUS * len(self.world.player.eyes())
        return zoom / eye_bonus

    def draw(self, surface: pygame.Surface) -> None:
        zoom = self._camera_zoom()
        size = (max(1, round(config.WIDTH / zoom)), max(1, round(config.HEIGHT / zoom)))
        if size != self._world_surface_size:
            self._world_surface = pygame.Surface(size)
            self._world_surface_size = size
        world_surface = self._world_surface

        real_width, real_height = config.WIDTH, config.HEIGHT
        config.WIDTH, config.HEIGHT = size
        try:
            camera = render.camera_for(self.world)
            render.draw_background(world_surface, camera, self.world.time)

            for food in self.world.foods:
                render.draw_food(world_surface, food, camera)
            for enemy in self.world.enemies:
                render.draw_creature(world_surface, enemy, camera, world=self.world)
            if not self.world.player.is_dead:
                render.draw_creature(
                    world_surface,
                    self.world.player,
                    camera,
                    self.active_groups,
                    self.small_font,
                    world=self.world,
                )
        finally:
            config.WIDTH, config.HEIGHT = real_width, real_height

        pygame.transform.smoothscale(world_surface, (real_width, real_height), surface)

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

        render.draw_energy_bar(surface, (16, y + 4, 220, 14), player.energy, player.max_energy)
        y += 24
        energy_line = (
            f"Энергия: {player.energy:.0f} / {player.max_energy:.0f}"
            f"   голод через {max(0.0, player.hunger_timer):.0f} с"
        )
        surface.blit(self.small_font.render(energy_line, True, config.FG_COLOR), (16, y))

        hint = self.small_font.render(
            "Цифры — двигатели, R — залечить дырки за энергию, Esc — выход. "
            + self.cheats.hint_line(),
            True,
            config.BORDER_COLOR,
        )
        surface.blit(hint, (16, config.HEIGHT - 28))

        status = self.cheats.status_line()
        if status is not None:
            cheat_line = self.small_font.render(status, True, config.ENEMY_SKIN_COLOR)
            surface.blit(cheat_line, (16, config.HEIGHT - 48))


class GameOverScene:
    """Существо погибло — показываем счёт и возвращаем в редактор."""

    def __init__(self, blueprint: Blueprint, kills: int) -> None:
        self.blueprint = blueprint
        self.kills = kills
        self.font = render.get_font(24)
        self.big_font = render.get_font(48, bold=True)
        self.time = 0.0
        self.next_scene = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (
            pygame.K_RETURN,
            pygame.K_KP_ENTER,
            pygame.K_SPACE,
        ):
            self.next_scene = EditorScene(self.blueprint, last_score=self.kills)

    def update(self, dt: float):
        self.time += dt
        scene, self.next_scene = self.next_scene, None
        return scene

    def draw(self, surface: pygame.Surface) -> None:
        render.draw_background(surface, render.calm_camera(self.time), self.time, calm=True)
        center_x = config.WIDTH // 2
        title = self.big_font.render("Существо погибло", True, config.ENEMY_SKIN_COLOR)
        surface.blit(title, title.get_rect(center=(center_x, config.HEIGHT // 2 - 60)))

        score = self.font.render(f"Съедено врагов: {self.kills}", True, config.FG_COLOR)
        surface.blit(score, score.get_rect(center=(center_x, config.HEIGHT // 2)))

        hint = self.font.render("Enter — собрать существо заново", True, config.BORDER_COLOR)
        surface.blit(hint, hint.get_rect(center=(center_x, config.HEIGHT // 2 + 50)))
