"""Экран сборки существа."""

from __future__ import annotations

import pygame

from evolution import config, creature, hexgrid, render
from evolution.creature import (
    EYE,
    EYE_LOOKS,
    EYE_LOOK_VECTORS,
    KINDS,
    LOOK_ENEMY,
    LOOK_FOOD,
    MANEUVER,
    PHOTOSYNTH,
    PROCESSOR,
    ROOT,
    THRUSTER,
    Blueprint,
    CellSpec,
    Muscle,
    cell_color,
    cell_cost,
    cell_upkeep,
    cell_work_upkeep,
    clamp_brake,
    default_blueprint,
    food_energy,
    Species,
)
from evolution.hexgrid import Coord
from evolution.i18n import HELP_KEYS, KEY_LINES, t
from evolution.menu import Menu

def origin() -> tuple[float, float]:
    return config.WIDTH * 0.36, config.HEIGHT * 0.5


def panel_x() -> int:
    return config.WIDTH - 420


# тесты кликают относительно центра сетки при стандартном окне
ORIGIN = (config.WINDOW_WIDTH * 0.36, config.WINDOW_HEIGHT * 0.5)

MUSCLE = "muscle"
"""Особый режим редактора: ставим не клетку, а верёвку между двумя клетками."""

MODES = (*KINDS, MUSCLE)


def kind_help(kind: str) -> list[str]:
    """Короткие строки про выбранный вид: как работает, цена, голод, бой."""
    kwargs = {
        "cost": cell_cost(kind),
        "upkeep": cell_upkeep(kind),
        "work": cell_work_upkeep(kind),
        "food": food_energy(kind),
        "chance": round(config.PHOTOSYNTH_UPKEEP_CHANCE * 100),
        "heat": config.THRUSTER_OVERHEAT_TIME,
        "cool": config.THRUSTER_COOLDOWN_TIME,
        "speed": config.PROCESS_SPEEDUP,
        "range": config.EYE_SENSE_RANGE,
        "gain": config.PHOTOSYNTH_ENERGY_GAIN,
    }
    return [t(key, **kwargs) for key in HELP_KEYS.get(kind, [])]


class EditorScene:
    """Собираем существо из гексов в пределах бюджета клеток."""

    def __init__(self, species: Species | Blueprint | None = None, last_score: int | None = None) -> None:
        if species is None:
            loaded = Species.load(creature.SAVE_PATH)
            species = loaded if loaded is not None else Species([default_blueprint()])
        elif isinstance(species, Blueprint):
            species = Species([species])
        self.species = species.copy()
        self.stage_index = 0
        self.kind = THRUSTER
        self.direction = 0
        self.group = 1
        self.look = LOOK_FOOD  # куда смотрит глаз, крутится колёсиком
        self.strength = 5  # сила мышцы, крутится колёсиком
        self.brake = 10  # сила манёвра 1..10 (10%..100%)
        self.muscle_start: Coord | None = None  # первый конец начатой мышцы
        self.last_score = last_score
        self.pan = [0.0, 0.0]  # смещение камеры редактора относительно ORIGIN
        self._dragging = False
        self._drag_anchor: tuple[int, int] | None = None
        self.font = render.get_font(20)
        self.small_font = render.get_font(16)
        self.big_font = render.get_font(34, bold=True)
        self.time = 0.0
        self.next_scene = None
        self._stage_hit: list[tuple[pygame.Rect, str, int | None]] = []
        # «Ставим» + настройки вида + описание: пока курсор здесь — виден kind_help
        self._kind_hover_rect = pygame.Rect(0, 0, 0, 0)
        self.menu = Menu(from_editor=True)

    @property
    def wants_quit(self) -> bool:
        return self.menu.wants_quit

    @property
    def blueprint(self) -> Blueprint:
        return self.species.stages[self.stage_index]

    def _budget(self) -> float:
        return self.species.budget(self.stage_index)

    # --- ввод ---

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.menu.handle_event(event):
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 2:
                # средняя кнопка — перетаскивание вида, не ставит клетку
                self._dragging = True
                self._drag_anchor = event.pos
                return
            if event.button == 1 and self._click_stage_ui(event.pos):
                return
            if event.pos[0] >= panel_x():
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
                elif self.kind == EYE:
                    self._cycle_look(step)
                elif self.kind == MANEUVER:
                    self._cycle_brake(step)
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
                if self.kind == EYE:
                    self._cycle_look(-1)
                elif self.kind == MANEUVER:
                    self._cycle_brake(-1)
                else:
                    self.direction = (self.direction - 1) % 6
            elif event.key in (pygame.K_e,):
                if self.kind == EYE:
                    self._cycle_look(1)
                elif self.kind == MANEUVER:
                    self._cycle_brake(1)
                else:
                    self.direction = (self.direction + 1) % 6
            elif pygame.K_1 <= event.key <= pygame.K_9:
                self.group = event.key - pygame.K_0
                if self.kind not in (THRUSTER, MUSCLE, MANEUVER):
                    self.kind = THRUSTER
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._start_game()
            elif event.key == pygame.K_LEFTBRACKET:
                self._set_stage(self.stage_index - 1)
            elif event.key == pygame.K_RIGHTBRACKET:
                self._set_stage(self.stage_index + 1)
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self._add_stage()
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self._remove_stage()

    def _cycle_look(self, step: int) -> None:
        index = EYE_LOOKS.index(self.look)
        self.look = EYE_LOOKS[(index + step) % len(EYE_LOOKS)]

    def _cycle_brake(self, step: int) -> None:
        self.brake = clamp_brake(self.brake + step)

    def _origin(self) -> tuple[float, float]:
        ox, oy = origin()
        return ox + self.pan[0], oy + self.pan[1]

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
            if self.blueprint.cost() + extra > self._budget() + 1e-6:
                return
            existing.kind = self.kind
            if self.kind == THRUSTER:
                existing.direction = self.direction
                existing.group = self.group
            elif self.kind == EYE:
                existing.look = self.look
            elif self.kind == MANEUVER:
                existing.group = self.group
                existing.brake = self.brake
            return
        if self.blueprint.cost() + cell_cost(self.kind) > self._budget() + 1e-6:
            return
        self.blueprint.place(
            CellSpec(coord, self.kind, self.direction, self.group, self.look, self.brake)
        )

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
        if self.blueprint.cost() + muscle.cost() <= self._budget() + 1e-6:
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

    def _set_stage(self, index: int) -> None:
        if 0 <= index < len(self.species.stages):
            self.stage_index = index
            self.muscle_start = None

    def _add_stage(self) -> None:
        if len(self.species.stages) >= config.STAGE_MAX:
            return
        last = self.species.stages[-1]
        self.species.stages.append(last.copy())
        self._set_stage(len(self.species.stages) - 1)

    def _remove_stage(self) -> None:
        if len(self.species.stages) <= 1:
            return
        del self.species.stages[self.stage_index]
        self._set_stage(min(self.stage_index, len(self.species.stages) - 1))

    def _click_stage_ui(self, pos: tuple[int, int]) -> bool:
        for rect, action, index in self._stage_hit:
            if not rect.collidepoint(pos):
                continue
            if action == "select" and index is not None:
                self._set_stage(index)
            elif action == "add":
                self._add_stage()
            elif action == "remove":
                self._remove_stage()
            return True
        return False

    def _start_game(self) -> None:
        from evolution.scenes import PlayScene  # поздний импорт: экраны ссылаются друг на друга

        if not self.species.valid():
            return
        self.species.save(creature.SAVE_PATH)
        self.next_scene = PlayScene(self.species)

    # --- игровой цикл ---

    def update(self, dt: float):
        if not self.menu.open:
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
        px = panel_x()
        corners = [(0, 0), (px - 20, 0), (0, config.HEIGHT), (px - 20, config.HEIGHT)]
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
            elif spec.kind == EYE:
                self._draw_eye_marks(surface, center, size, spec.look)
            elif spec.kind == MANEUVER:
                self._draw_maneuver_marks(surface, center, spec.group, spec.brake)

        self._draw_muscles(surface, size)
        self._draw_panel(surface)
        self.menu.draw(surface)

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

    def _draw_eye_marks(
        self,
        surface: pygame.Surface,
        center: tuple[float, float],
        size: float,
        look: str,
    ) -> None:
        """Зрачок: у компаса смещён на сторону света, у еды/врага — цветной."""
        compass = EYE_LOOK_VECTORS.get(look)
        if look == LOOK_FOOD:
            color = config.FOOD_COLOR
            dx, dy = 0.0, 0.0
        elif look == LOOK_ENEMY:
            color = config.ENEMY_SKIN_COLOR
            dx, dy = 0.0, 0.0
        else:
            color = config.OUTLINE_COLOR
            dx, dy = compass if compass is not None else (0.0, 0.0)
        pupil = (center[0] + dx * size * 0.28, center[1] + dy * size * 0.28)
        pygame.draw.circle(surface, color, (int(pupil[0]), int(pupil[1])), int(size * 0.22))

    def _draw_maneuver_marks(
        self,
        surface: pygame.Surface,
        center: tuple[float, float],
        group: int,
        brake: int,
    ) -> None:
        label = self.font.render(f"{group}·{brake * 10}%", True, config.OUTLINE_COLOR)
        surface.blit(label, label.get_rect(center=center))

    def _draw_stage_row(self, surface: pygame.Surface, x: int, y: int) -> int:
        """Кнопки этапов, плюс и минус — куда ткнули, запоминаем в `_stage_hit`."""
        self._stage_hit = []
        surface.blit(self.font.render(t("editor.stages"), True, config.FG_COLOR), (x, y))
        y += 28
        cursor = x
        for i in range(len(self.species.stages)):
            label = str(i + 1)
            text = self.font.render(label, True, config.OUTLINE_COLOR)
            pad_x, pad_y = 10, 4
            rect = pygame.Rect(cursor, y, text.get_width() + pad_x * 2, text.get_height() + pad_y * 2)
            fill = config.THRUSTER_COLOR if i == self.stage_index else config.GRID_COLOR
            pygame.draw.rect(surface, fill, rect, border_radius=6)
            surface.blit(text, text.get_rect(center=rect.center))
            self._stage_hit.append((rect, "select", i))
            cursor = rect.right + 6
        plus = self.font.render("+", True, config.FG_COLOR)
        plus_rect = pygame.Rect(cursor, y, 28, 28)
        pygame.draw.rect(surface, config.BORDER_COLOR, plus_rect, width=1, border_radius=6)
        surface.blit(plus, plus.get_rect(center=plus_rect.center))
        self._stage_hit.append((plus_rect, "add", None))
        cursor = plus_rect.right + 6
        minus = self.font.render("−", True, config.FG_COLOR)
        minus_rect = pygame.Rect(cursor, y, 28, 28)
        pygame.draw.rect(surface, config.BORDER_COLOR, minus_rect, width=1, border_radius=6)
        surface.blit(minus, minus.get_rect(center=minus_rect.center))
        self._stage_hit.append((minus_rect, "remove", None))
        return y + 34

    def _draw_panel(self, surface: pygame.Surface) -> None:
        x = panel_x()
        y = 40
        title = self.big_font.render(t("editor.title"), True, config.FG_COLOR)
        surface.blit(title, (x, y))
        y += 50
        y = self._draw_stage_row(surface, x, y)
        y += 8

        used = self.blueprint.cost()
        budget = self._budget()
        color = config.FG_COLOR if used <= budget + 1e-6 else (230, 130, 120)
        surface.blit(
            self.font.render(t("editor.points", used=used, budget=budget), True, color), (x, y)
        )
        y += 28
        surface.blit(
            self.font.render(t("editor.cells", n=len(self.blueprint)), True, config.FG_COLOR),
            (x, y),
        )
        y += 28

        # аппетит: сколько тело просит за один удар голода и какой у него бак
        appetite = self.blueprint.appetite()
        surface.blit(
            self.font.render(
                t("editor.appetite", appetite=appetite, tank=self.blueprint.tank()),
                True,
                config.FG_COLOR,
            ),
            (x, y),
        )
        y += 24
        cap_hint = t("editor.cap0") if self.stage_index == 0 else t("editor.capn")
        surface.blit(self.small_font.render(cap_hint, True, config.BORDER_COLOR), (x, y))
        y += 22
        if not self.species.valid():
            surface.blit(
                self.small_font.render(t("editor.overbudget"), True, (230, 130, 120)),
                (x, y),
            )
            y += 22

        # без еды и без фотосинтеза тело только тратит — и умрёт с голоду
        kinds = {spec.kind for spec in self.blueprint.cells.values()}
        if PROCESSOR not in kinds and PHOTOSYNTH not in kinds:
            warn = (230, 130, 120)
            for key in ("editor.starve1", "editor.starve2"):
                surface.blit(self.font.render(t(key), True, warn), (x, y))
                y += 26
        y += 8

        kind_top = y
        surface.blit(
            self.font.render(t("editor.placing", kind=t(f"kind.{self.kind}")), True, config.FG_COLOR),
            (x, y),
        )
        y += 26
        if self.kind == EYE:
            surface.blit(
                self.small_font.render(
                    t("editor.looks", look=t(f"look.{self.look}")),
                    True,
                    config.FG_COLOR,
                ),
                (x, y),
            )
            y += 20
        if self.kind == MUSCLE:
            surface.blit(
                self.small_font.render(
                    t("editor.muscle", strength=self.strength, group=self.group),
                    True,
                    config.FG_COLOR,
                ),
                (x, y),
            )
            y += 20
        if self.kind == MANEUVER:
            surface.blit(
                self.small_font.render(
                    t("editor.maneuver", percent=self.brake * 10, group=self.group),
                    True,
                    config.FG_COLOR,
                ),
                (x, y),
            )
            y += 20
        if self.kind == THRUSTER:
            surface.blit(
                self.small_font.render(
                    t("editor.thruster_btn", group=self.group), True, config.FG_COLOR
                ),
                (x, y),
            )
            y += 20
            thrust = self.small_font.render(t("editor.thrust_here"), True, config.FG_COLOR)
            surface.blit(thrust, (x, y))
            self._draw_direction_preview(surface, (x + thrust.get_width() + 36, y + 8))
            y += 40
        mouse = pygame.mouse.get_pos()
        if self._kind_hover_rect.collidepoint(mouse):
            for line in kind_help(self.kind):
                surface.blit(self.small_font.render(line, True, config.FG_COLOR), (x, y))
                y += 20
        self._kind_hover_rect = pygame.Rect(x, kind_top, config.WIDTH - x, y - kind_top)
        if self.kind == MUSCLE and self.muscle_start is not None:
            surface.blit(
                self.small_font.render(t("editor.muscle_next"), True, config.FOOD_COLOR),
                (x, y),
            )
            y += 20

        y += 8
        for key in KEY_LINES:
            surface.blit(self.small_font.render(t(key), True, config.FG_COLOR), (x, y))
            y += 20

        if self.last_score is not None:
            y += 20
            surface.blit(
                self.font.render(t("editor.last", n=self.last_score), True, config.FOOD_COLOR),
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
