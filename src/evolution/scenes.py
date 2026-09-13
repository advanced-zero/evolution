"""Экраны игры и переходы между ними: меню → редактор → бой → гибель."""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from evolution import config, render, saves, settings
from evolution.creature import Blueprint, Species
from evolution.editor import EditorScene
from evolution.i18n import t
from evolution.menu import Menu
from evolution.world import World

__all__ = ["MainMenuScene", "EditorScene", "PlayScene", "GameOverScene"]

PAGE_ROOT = "root"
PAGE_SAVES = "saves"
PAGE_OPTIONS = "options"
PAGE_CONFIRM_QUIT = "confirm_quit"


@dataclass
class _MenuItem:
    action: str
    rect: pygame.Rect
    payload: str | None = None


class MainMenuScene:
    """Первый экран: играть, сохранения, настройки, выход."""

    def __init__(self) -> None:
        self.page = PAGE_ROOT
        self.index = 0
        self.wants_quit = False
        self.font = render.get_font(22)
        self.big_font = render.get_font(48, bold=True)
        self.time = 0.0
        self.next_scene = None
        self._items: list[_MenuItem] = []

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._back()
                return
            if event.key in (pygame.K_UP, pygame.K_w):
                self._move(-1)
                return
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self._move(1)
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate(self.index)
                return
        elif event.type == pygame.MOUSEMOTION:
            for i, item in enumerate(self._items):
                if item.rect.collidepoint(event.pos):
                    self.index = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, item in enumerate(self._items):
                if item.rect.collidepoint(event.pos):
                    self.index = i
                    self._activate(i)
                    break

    def update(self, dt: float):
        self.time += dt
        scene, self.next_scene = self.next_scene, None
        return scene

    def _back(self) -> None:
        if self.page == PAGE_ROOT:
            return
        self.page = PAGE_ROOT
        self.index = 0

    def _move(self, step: int) -> None:
        n = len(self._specs())
        if n == 0:
            return
        self.index = (self.index + step) % n

    def _specs(self) -> list[tuple[str, str, str | None]]:
        if self.page == PAGE_ROOT:
            return [
                ("play", t("main.play"), None),
                ("saves", t("main.saves"), None),
                ("options", t("menu.options"), None),
                ("quit", t("menu.quit"), None),
            ]
        if self.page == PAGE_SAVES:
            rows: list[tuple[str, str, str | None]] = [("new", t("main.new"), None)]
            current = saves.current_id()
            for info in saves.list_saves():
                label = (
                    t("saves.current", name=info.name)
                    if info.id == current
                    else info.name
                )
                rows.append(("open", label, info.id))
            rows.append(("back", t("menu.back"), None))
            return rows
        if self.page == PAGE_OPTIONS:
            on = t("opt.fullscreen.on") if settings.fullscreen else t("opt.fullscreen.off")
            lang = t("opt.lang.ru") if settings.language == settings.LANG_RU else t("opt.lang.en")
            return [
                ("fullscreen", t("opt.fullscreen", value=on), None),
                ("language", t("opt.language", value=lang), None),
                ("back", t("menu.back"), None),
            ]
        yes, no = t("menu.yes"), t("menu.no")
        return [("confirm_quit", yes, None), ("cancel", no, None)]

    def _activate(self, index: int) -> None:
        specs = self._specs()
        if not (0 <= index < len(specs)):
            return
        action, _label, payload = specs[index]
        if action == "play":
            self._play()
        elif action == "saves":
            self.page = PAGE_SAVES
            self.index = 0
        elif action == "options":
            self.page = PAGE_OPTIONS
            self.index = 0
        elif action == "quit":
            self.page = PAGE_CONFIRM_QUIT
            self.index = 0
        elif action == "back":
            self._back()
        elif action == "fullscreen":
            settings.toggle_fullscreen()
        elif action == "language":
            settings.cycle_language()
        elif action == "confirm_quit":
            self.wants_quit = True
        elif action == "cancel":
            self.page = PAGE_ROOT
            self.index = 0
        elif action == "new":
            save_id, species = saves.create_new()
            self.next_scene = EditorScene(species, save_id=save_id)
        elif action == "open" and payload:
            saves.set_current(payload)
            species = saves.load(payload)
            if species is None:
                return
            self.next_scene = EditorScene(species, save_id=payload)

    def _play(self) -> None:
        current = saves.load_current()
        save_id = saves.current_id()
        if current is None or save_id is None:
            save_id, species = saves.create_new()
            self.next_scene = EditorScene(species, save_id=save_id)
            return
        if current.valid():
            self.next_scene = PlayScene(current, save_id=save_id)
        else:
            self.next_scene = EditorScene(current, save_id=save_id)

    def draw(self, surface: pygame.Surface) -> None:
        render.draw_background(surface, render.calm_camera(self.time), self.time, calm=True)
        specs = self._specs()
        panel_h = 90 + 50 * len(specs) + 36
        panel = pygame.Rect(0, 0, 520, min(panel_h, config.HEIGHT - 40))
        panel.center = (config.WIDTH // 2, config.HEIGHT // 2)
        pygame.draw.rect(surface, config.MENU_PANEL, panel, border_radius=12)
        pygame.draw.rect(surface, config.BORDER_COLOR, panel, width=1, border_radius=12)

        title_key = {
            PAGE_ROOT: "main.title",
            PAGE_SAVES: "saves.title",
            PAGE_OPTIONS: "opt.title",
            PAGE_CONFIRM_QUIT: "menu.confirm_quit",
        }[self.page]
        title_font = self.font if self.page == PAGE_CONFIRM_QUIT else self.big_font
        title = title_font.render(t(title_key), True, config.FG_COLOR)
        surface.blit(title, title.get_rect(center=(panel.centerx, panel.top + 36)))

        self._items = []
        y = panel.top + 80
        for i, (action, label, payload) in enumerate(specs):
            rect = pygame.Rect(panel.left + 40, y, panel.width - 80, 40)
            hot = i == self.index
            pygame.draw.rect(
                surface,
                config.MENU_BUTTON_HOT if hot else config.MENU_BUTTON,
                rect,
                border_radius=8,
            )
            text = self.font.render(label, True, config.FG_COLOR)
            surface.blit(text, text.get_rect(center=rect.center))
            self._items.append(_MenuItem(action, rect, payload))
            y += 50
        if self._items:
            self.index %= len(self._items)


class PlayScene:
    """Бой: плаваем, таранимся, подбираем клетки."""

    def __init__(self, species: Species | Blueprint, save_id: str | None = None) -> None:
        if isinstance(species, Blueprint):
            species = Species([species])
        self.species = species.copy()
        self.save_id = save_id
        self.world = World(self.species)
        self.active_groups: set[int] = set()
        self.repairing = False
        self.font = render.get_font(20)
        self.small_font = render.get_font(16)
        self.death_delay = 0.0
        self.next_scene = None
        self._world_surface: pygame.Surface | None = None
        self._world_surface_size: tuple[int, int] | None = None
        self.menu = Menu(from_editor=False)

    @property
    def wants_quit(self) -> bool:
        return self.menu.wants_quit

    def handle_event(self, event: pygame.event.Event) -> None:
        was_open = self.menu.open
        if self.menu.handle_event(event):
            if self.menu.open and not was_open:
                self.active_groups.clear()
                self.repairing = False
            return
        if event.type == pygame.KEYDOWN and pygame.K_1 <= event.key <= pygame.K_9:
            self.active_groups.add(event.key - pygame.K_0)
        elif event.type == pygame.KEYUP and pygame.K_1 <= event.key <= pygame.K_9:
            self.active_groups.discard(event.key - pygame.K_0)
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
            self.repairing = True
        elif event.type == pygame.KEYUP and event.key == pygame.K_r:
            self.repairing = False

    def update(self, dt: float):
        if self.menu.wants_editor:
            return EditorScene(self.species, save_id=self.save_id)
        if self.menu.wants_menu:
            return MainMenuScene()
        if self.menu.open:
            return None
        self.world.update(dt, self.active_groups, self.repairing)
        if self.world.player.is_dead:
            self.death_delay += dt
            if self.death_delay > 1.2:
                return GameOverScene(self.species, self.world.kills, save_id=self.save_id)
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
            for crumb in self.world.crumbs:
                render.draw_crumb(world_surface, crumb, camera)
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
        self.menu.draw(surface)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        player = self.world.player
        stages = len(player.species.stages) if player.species else 1
        groups = " ".join(str(g) for g in sorted(player.groups())) or t("play.thrusters.none")
        lines = [
            t("play.kills", n=self.world.kills),
            t("play.stage", cur=player.stage_index + 1, total=stages)
            + (t("play.growing") if player.evolving else ""),
            t("play.cells", alive=len(player.alive_cells), total=len(player.blueprint.cells)),
            t("play.thrusters", groups=groups),
        ]
        y = 14
        for line in lines:
            surface.blit(self.font.render(line, True, config.FG_COLOR), (16, y))
            y += 26

        render.draw_energy_bar(surface, (16, y + 4, 220, 14), player.energy, player.max_energy)
        y += 24
        energy_line = t(
            "play.energy",
            cur=player.energy,
            max=player.max_energy,
            hunger=max(0.0, player.hunger_timer),
        )
        surface.blit(self.small_font.render(energy_line, True, config.FG_COLOR), (16, y))
        y += 20
        cost = player.next_evolve_cost()
        if player.evolving:
            grow = t("play.grow.evolving")
        elif cost is not None:
            grow = t("play.grow.need", need=max(0.0, cost - player.energy))
        else:
            grow = t("play.grow.done")
        surface.blit(self.small_font.render(grow, True, config.BORDER_COLOR), (16, y))

        hint = self.small_font.render(t("play.hint"), True, config.BORDER_COLOR)
        surface.blit(hint, (16, config.HEIGHT - 28))


class GameOverScene:
    """Существо погибло — показываем счёт и возвращаем в редактор."""

    def __init__(self, species: Species | Blueprint, kills: int, save_id: str | None = None) -> None:
        if isinstance(species, Blueprint):
            species = Species([species])
        self.species = species
        self.kills = kills
        self.save_id = save_id
        self.font = render.get_font(24)
        self.big_font = render.get_font(48, bold=True)
        self.time = 0.0
        self.next_scene = None
        self.menu = Menu(from_editor=False)

    @property
    def wants_quit(self) -> bool:
        return self.menu.wants_quit

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.menu.handle_event(event):
            return
        if event.type == pygame.KEYDOWN and event.key in (
            pygame.K_RETURN,
            pygame.K_KP_ENTER,
            pygame.K_SPACE,
        ):
            self.next_scene = EditorScene(self.species, last_score=self.kills, save_id=self.save_id)

    def update(self, dt: float):
        if self.menu.wants_editor:
            return EditorScene(self.species, last_score=self.kills, save_id=self.save_id)
        if self.menu.wants_menu:
            return MainMenuScene()
        if not self.menu.open:
            self.time += dt
        scene, self.next_scene = self.next_scene, None
        return scene

    def draw(self, surface: pygame.Surface) -> None:
        render.draw_background(surface, render.calm_camera(self.time), self.time, calm=True)
        center_x = config.WIDTH // 2
        title = self.big_font.render(t("over.title"), True, config.ENEMY_SKIN_COLOR)
        surface.blit(title, title.get_rect(center=(center_x, config.HEIGHT // 2 - 60)))

        score = self.font.render(t("over.kills", n=self.kills), True, config.FG_COLOR)
        surface.blit(score, score.get_rect(center=(center_x, config.HEIGHT // 2)))

        hint = self.font.render(t("over.hint"), True, config.BORDER_COLOR)
        surface.blit(hint, hint.get_rect(center=(center_x, config.HEIGHT // 2 + 50)))
        self.menu.draw(surface)
