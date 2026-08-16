"""Экран сборки существа."""

from __future__ import annotations

import pygame

from evolution import config, creature, hexgrid, render
from evolution.creature import (
    BONE,
    KINDS,
    PROCESSOR,
    ROOT,
    SKIN,
    THRUSTER,
    Blueprint,
    CellSpec,
    Muscle,
    cell_color,
    cell_cost,
    cell_upkeep,
    default_blueprint,
)
from evolution.hexgrid import Coord

ORIGIN = (config.WIDTH * 0.36, config.HEIGHT * 0.5)
PANEL_X = config.WIDTH - 420

MUSCLE = "muscle"
"""Особый режим редактора: ставим не клетку, а верёвку между двумя клетками."""

MODES = (*KINDS, MUSCLE)

KIND_NAMES = {
    SKIN: "кожа",
    BONE: "кость",
    THRUSTER: "двигатель",
    PROCESSOR: "переработчик",
    MUSCLE: "мышца",
}

HELP_LINES = [
    "ЛКМ — поставить клетку",
    "ПКМ — убрать клетку",
    "Tab — сменить, что ставим",
    "Q, E или колесо — повернуть двигатель",
    "1..9 — кнопка двигателя или мышцы",
    "Мышца: клик по клетке, потом по второй",
    "колесо — сила мышцы, ПКМ — снять",
    "Стрелки или средняя кнопка мыши — прокрутка вида",
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
        self.strength = 5  # сила мышцы, крутится колёсиком
        self.muscle_start: Coord | None = None  # первый конец начатой мышцы
        self.last_score = last_score
        self.pan = [0.0, 0.0]  # смещение камеры редактора относительно ORIGIN
        self._dragging = False
        self._drag_anchor: tuple[int, int] | None = None
        self.font = render.get_font(20)
        self.big_font = render.get_font(34, bold=True)
        self.time = 0.0
        self.next_scene = None

    # --- ввод ---

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 2:
                # средняя кнопка — перетаскивание вида, не ставит клетку
                self._dragging = True
                self._drag_anchor = event.pos
                return
            coord = self._coord_at(event.pos)
            if event.button == 1:
                self._place_muscle(coord) if self.kind == MUSCLE else self._place(coord)
            elif event.button == 3:
                self._erase(coord)
            elif event.button in (4, 5):
                step = 1 if event.button == 4 else -1
                if self.kind == MUSCLE:
                    # колёсико крутит силу мышцы, а не поворот двигателя
                    self.strength = max(
                        1, min(config.MUSCLE_MAX_STRENGTH, self.strength + step)
                    )
                else:
                    self.direction = (self.direction + step) % 6

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._dragging = False
                self._drag_anchor = None

        elif event.type == pygame.MOUSEMOTION:
            if self._dragging and self._drag_anchor is not None:
                self.pan[0] += event.pos[0] - self._drag_anchor[0]
                self.pan[1] += event.pos[1] - self._drag_anchor[1]
                self._drag_anchor = event.pos

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self.kind = MODES[(MODES.index(self.kind) + 1) % len(MODES)]
                self.muscle_start = None
            elif event.key in (pygame.K_q,):
                self.direction = (self.direction - 1) % 6
            elif event.key in (pygame.K_e,):
                self.direction = (self.direction + 1) % 6
            elif pygame.K_1 <= event.key <= pygame.K_9:
                self.group = event.key - pygame.K_0
                if self.kind not in (THRUSTER, MUSCLE):
                    self.kind = THRUSTER
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._start_game()

    def _origin(self) -> tuple[float, float]:
        return ORIGIN[0] + self.pan[0], ORIGIN[1] + self.pan[1]

    def _coord_at(self, pos: tuple[int, int]) -> Coord:
        ox, oy = self._origin()
        return hexgrid.pixel_to_hex(pos[0] - ox, pos[1] - oy, config.EDITOR_HEX_SIZE)

    def _place(self, coord: Coord) -> None:
        existing = self.blueprint.cells.get(coord)
        if existing is not None:
            # клик по уже стоящей клетке перестраивает её в выбранный вид
            if coord == ROOT:
                return
            extra = cell_cost(self.kind) - cell_cost(existing.kind)
            if self.blueprint.cost() + extra > config.CELL_BUDGET:
                return
            existing.kind = self.kind
            if self.kind == THRUSTER:
                existing.direction = self.direction
                existing.group = self.group
            return
        if self.blueprint.cost() + cell_cost(self.kind) > config.CELL_BUDGET:
            return
        self.blueprint.place(CellSpec(coord, self.kind, self.direction, self.group))

    def _place_muscle(self, coord: Coord) -> None:
        """Первый клик задаёт один конец верёвки, второй — другой."""
        if coord not in self.blueprint.cells:
            return
        if self.muscle_start is None:
            self.muscle_start = coord
            return
        if coord == self.muscle_start:
            self.muscle_start = None  # ткнули туда же — передумали
            return
        muscle = Muscle(self.muscle_start, coord, self.group, self.strength)
        if self.blueprint.cost() + muscle.cost() <= config.CELL_BUDGET:
            self.blueprint.add_muscle(muscle)
        self.muscle_start = None

    def _erase(self, coord: Coord) -> None:
        """ПКМ: в режиме мышцы снимает верёвку, иначе убирает клетку."""
        if self.kind == MUSCLE:
            if self.muscle_start is not None:
                self.muscle_start = None
                return
            for muscle in self.blueprint.muscles_at(coord):
                self.blueprint.muscles.remove(muscle)
                return
            return
        self.blueprint.remove(coord)

    def _start_game(self) -> None:
        from evolution.scenes import PlayScene  # поздний импорт: экраны ссылаются друг на друга

        self.blueprint.save(creature.SAVE_PATH)
        self.next_scene = PlayScene(self.blueprint)

    # --- игровой цикл ---

    def update(self, dt: float):
        self.time += dt
        keys = pygame.key.get_pressed()
        move = config.EDITOR_PAN_SPEED * dt
        if keys[pygame.K_LEFT]:
            self.pan[0] += move
        if keys[pygame.K_RIGHT]:
            self.pan[0] -= move
        if keys[pygame.K_UP]:
            self.pan[1] += move
        if keys[pygame.K_DOWN]:
            self.pan[1] -= move
        scene, self.next_scene = self.next_scene, None
        return scene

    # --- отрисовка ---

    def _visible_coords(self) -> list[Coord]:
        """Гексы, видимые в области редактора сейчас: сетка не ограничена
        кольцами, поэтому вместо заранее посчитанного списка каждый кадр
        считаем прямоугольник координат, покрывающий текущий вид камеры.
        """
        ox, oy = self._origin()
        size = config.EDITOR_HEX_SIZE
        corners = [(0, 0), (PANEL_X - 20, 0), (0, config.HEIGHT), (PANEL_X - 20, config.HEIGHT)]
        qs, rs = [], []
        for x, y in corners:
            q, r = hexgrid.pixel_to_hex(x - ox, y - oy, size)
            qs.append(q)
            rs.append(r)
        pad = 1
        return [
            (q, r)
            for q in range(min(qs) - pad, max(qs) + pad + 1)
            for r in range(min(rs) - pad, max(rs) + pad + 1)
        ]

    def draw(self, surface: pygame.Surface) -> None:
        render.draw_background(surface, render.calm_camera(self.time), self.time, calm=True)
        size = config.EDITOR_HEX_SIZE
        ox, oy = self._origin()

        for coord in self._visible_coords():
            px, py = hexgrid.hex_to_pixel(coord, size)
            center = (ox + px, oy + py)
            spec = self.blueprint.cells.get(coord)
            if spec is None:
                color = config.BORDER_COLOR if self.blueprint.can_place(coord) else config.GRID_COLOR
                render.draw_hex(surface, center, size * 0.94, color, width=1)
                continue

            render.draw_hex(surface, center, size * 0.94, cell_color(coord, spec))

            if spec.kind == THRUSTER:
                self._draw_thruster_marks(surface, center, size, spec.direction, spec.group)

        self._draw_muscles(surface, size)
        self._draw_panel(surface)

    def _cell_center(self, coord: Coord, size: float) -> tuple[float, float]:
        ox, oy = self._origin()
        px, py = hexgrid.hex_to_pixel(coord, size)
        return ox + px, oy + py

    def _draw_muscles(self, surface: pygame.Surface, size: float) -> None:
        """Мышцы — верёвки поверх тела; толщина показывает силу."""
        for muscle in self.blueprint.muscles:
            a = self._cell_center(muscle.a, size)
            b = self._cell_center(muscle.b, size)
            width = 2 + muscle.strength // 3
            pygame.draw.line(surface, config.MUSCLE_COLOR, a, b, width)
            middle = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            label = self.font.render(f"{muscle.group}·{muscle.strength}", True, config.FG_COLOR)
            surface.blit(label, label.get_rect(center=middle))

        if self.muscle_start is not None:
            # начатая мышца тянется за курсором
            start = self._cell_center(self.muscle_start, size)
            pygame.draw.line(surface, config.MUSCLE_COLOR, start, pygame.mouse.get_pos(), 2)

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

        used = self.blueprint.cost()
        color = config.FG_COLOR if used < config.CELL_BUDGET else (230, 130, 120)
        surface.blit(
            self.font.render(f"Очки: {used} / {config.CELL_BUDGET}", True, color), (x, y)
        )
        y += 28
        surface.blit(
            self.font.render(
                f"Клеток: {len(self.blueprint)}   (кость стоит {cell_cost(BONE)})",
                True,
                config.BORDER_COLOR,
            ),
            (x, y),
        )
        y += 28

        # аппетит: сколько тело просит за один удар голода и какой у него бак
        appetite = sum(
            cell_upkeep(spec.kind, coord == ROOT)
            for coord, spec in self.blueprint.cells.items()
        )
        surface.blit(
            self.font.render(
                f"Аппетит: {appetite:.0f}   бак: {appetite * config.ENERGY_RESERVE:.0f}",
                True,
                config.BORDER_COLOR,
            ),
            (x, y),
        )
        y += 28

        # без переработчика существо не сможет добыть ни капли энергии
        if not any(spec.kind == PROCESSOR for spec in self.blueprint.cells.values()):
            surface.blit(
                self.font.render("Без переработчика есть нечем!", True, (230, 130, 120)), (x, y)
            )
        y += 34

        surface.blit(
            self.font.render(f"Ставим: {KIND_NAMES[self.kind]}", True, config.FG_COLOR), (x, y)
        )
        y += 28
        if self.kind == BONE:
            surface.blit(
                self.font.render("Не гнётся, держит удар и не ест", True, config.BORDER_COLOR),
                (x, y),
            )
            y += 28
        if self.kind == PROCESSOR:
            surface.blit(
                self.font.render("Топит обломки рядом и кормит тело", True, config.BORDER_COLOR),
                (x, y),
            )
            y += 28
        if self.kind == MUSCLE:
            for line in (
                f"Сила: {self.strength} (колесо)   кнопка: {self.group}",
                f"Цена — по очку за клетку длины",
                "Стягивает концы — тело выгибается дугой",
            ):
                surface.blit(self.font.render(line, True, config.BORDER_COLOR), (x, y))
                y += 26
            if self.muscle_start is not None:
                surface.blit(
                    self.font.render("Теперь укажи второй конец", True, config.FOOD_COLOR), (x, y)
                )
                y += 26
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
