"""Экран сборки существа."""

from __future__ import annotations

import pygame

from evolution import config, creature, hexgrid, render
from evolution.creature import ROOT, SKIN, THRUSTER, Blueprint, CellSpec, default_blueprint
from evolution.hexgrid import Coord

ORIGIN = (config.WIDTH * 0.36, config.HEIGHT * 0.5)
PANEL_X = config.WIDTH - 420

HELP_LINES = [
    "ЛКМ — поставить клетку",
    "ПКМ — убрать клетку",
    "Tab — кожа / двигатель",
    "Q, E или колесо — повернуть",
    "1..9 — кнопка двигателя",
    "Enter — играть",
    "Esc — выход",
]


class EditorScene:
    """Собираем существо из гексов в пределах бюджета клеток."""

    def __init__(self, blueprint: Blueprint | None = None, last_score: int | None = None) -> None:
        if blueprint is None:
            blueprint = Blueprint.load(creature.SAVE_PATH) or default_blueprint()
        self.blueprint = blueprint.copy()
        self.kind = THRUSTER
        self.direction = 0
        self.group = 1
        self.last_score = last_score
        self.grid = hexgrid.spiral(config.EDITOR_RADIUS)
        self.font = render.get_font(20)
        self.big_font = render.get_font(34, bold=True)
        self.next_scene = None

    # --- ввод ---

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN:
            coord = self._coord_at(event.pos)
            if event.button == 1:
                self._place(coord)
            elif event.button == 3:
                self.blueprint.remove(coord)
            elif event.button == 4:
                self.direction = (self.direction + 1) % 6
            elif event.button == 5:
                self.direction = (self.direction - 1) % 6

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self.kind = SKIN if self.kind == THRUSTER else THRUSTER
            elif event.key in (pygame.K_q,):
                self.direction = (self.direction - 1) % 6
            elif event.key in (pygame.K_e,):
                self.direction = (self.direction + 1) % 6
            elif pygame.K_1 <= event.key <= pygame.K_9:
                self.group = event.key - pygame.K_0
                self.kind = THRUSTER
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._start_game()

    def _coord_at(self, pos: tuple[int, int]) -> Coord:
        return hexgrid.pixel_to_hex(pos[0] - ORIGIN[0], pos[1] - ORIGIN[1], config.EDITOR_HEX_SIZE)

    def _place(self, coord: Coord) -> None:
        if hexgrid.distance(ROOT, coord) > config.EDITOR_RADIUS:
            return
        existing = self.blueprint.cells.get(coord)
        if existing is not None:
            # клик по уже стоящему двигателю перенастраивает его
            if self.kind == THRUSTER and coord != ROOT:
                existing.kind = THRUSTER
                existing.direction = self.direction
                existing.group = self.group
            return
        if len(self.blueprint) >= config.CELL_BUDGET:
            return
        self.blueprint.place(CellSpec(coord, self.kind, self.direction, self.group))

    def _start_game(self) -> None:
        from evolution.scenes import PlayScene  # поздний импорт: экраны ссылаются друг на друга

        self.blueprint.save(creature.SAVE_PATH)
        self.next_scene = PlayScene(self.blueprint)

    # --- игровой цикл ---

    def update(self, dt: float):
        scene, self.next_scene = self.next_scene, None
        return scene

    # --- отрисовка ---

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(config.BG_COLOR)
        size = config.EDITOR_HEX_SIZE

        for coord in self.grid:
            px, py = hexgrid.hex_to_pixel(coord, size)
            center = (ORIGIN[0] + px, ORIGIN[1] + py)
            spec = self.blueprint.cells.get(coord)
            if spec is None:
                color = config.BORDER_COLOR if self.blueprint.can_place(coord) else config.GRID_COLOR
                render.draw_hex(surface, center, size * 0.94, color, width=1)
                continue

            if coord == ROOT:
                color = config.CORE_COLOR
            elif spec.kind == THRUSTER:
                color = config.THRUSTER_COLOR
            else:
                color = config.SKIN_COLOR
            render.draw_hex(surface, center, size * 0.94, color)

            if spec.kind == THRUSTER:
                self._draw_thruster_marks(surface, center, size, spec.direction, spec.group)

        self._draw_panel(surface)

    def _draw_thruster_marks(
        self,
        surface: pygame.Surface,
        center: tuple[float, float],
        size: float,
        direction: int,
        group: int,
    ) -> None:
        dx, dy = hexgrid.direction_vector(direction)
        tip = (center[0] + dx * size * 0.85, center[1] + dy * size * 0.85)
        pygame.draw.line(surface, config.OUTLINE_COLOR, center, tip, 3)
        label = self.font.render(str(group), True, config.OUTLINE_COLOR)
        surface.blit(label, label.get_rect(center=center))

    def _draw_panel(self, surface: pygame.Surface) -> None:
        x = PANEL_X
        y = 40
        title = self.big_font.render("Сборка существа", True, config.FG_COLOR)
        surface.blit(title, (x, y))
        y += 50

        used = len(self.blueprint)
        color = config.FG_COLOR if used < config.CELL_BUDGET else (230, 130, 120)
        surface.blit(
            self.font.render(f"Клеток: {used} / {config.CELL_BUDGET}", True, color), (x, y)
        )
        y += 34

        kind_name = "двигатель" if self.kind == THRUSTER else "кожа"
        surface.blit(self.font.render(f"Ставим: {kind_name}", True, config.FG_COLOR), (x, y))
        y += 28
        if self.kind == THRUSTER:
            surface.blit(
                self.font.render(f"Кнопка двигателя: {self.group}", True, config.FG_COLOR), (x, y)
            )
            y += 28
            surface.blit(self.font.render("Толкает сюда:", True, config.FG_COLOR), (x, y))
            self._draw_direction_preview(surface, (x + 190, y + 10))
            y += 46

        y += 10
        for line in HELP_LINES:
            surface.blit(self.font.render(line, True, config.BORDER_COLOR), (x, y))
            y += 26

        if self.last_score is not None:
            y += 20
            surface.blit(
                self.font.render(f"Прошлый заплыв: {self.last_score} врагов", True, config.FOOD_COLOR),
                (x, y),
            )

    def _draw_direction_preview(self, surface: pygame.Surface, center: tuple[float, float]) -> None:
        render.draw_hex(surface, center, 16, config.THRUSTER_COLOR)
        dx, dy = hexgrid.direction_vector(self.direction)
        pygame.draw.line(
            surface,
            config.FG_COLOR,
            center,
            (center[0] + dx * 34, center[1] + dy * 34),
            4,
        )
        # с обратной стороны бьёт «выхлоп»
        pygame.draw.line(
            surface,
            config.FLAME_COLOR,
            (center[0] - dx * 16, center[1] - dy * 16),
            (center[0] - dx * 30, center[1] - dy * 30),
            4,
        )
