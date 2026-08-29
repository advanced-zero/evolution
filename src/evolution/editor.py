"""Экран сборки существа."""

from __future__ import annotations

import pygame

from evolution import config, creature, hexgrid, render
from evolution.creature import (
    BONE,
    EYE,
    EYE_LOOK_NAMES,
    EYE_LOOKS,
    EYE_LOOK_VECTORS,
    KINDS,
    LOOK_ENEMY,
    LOOK_FOOD,
    PHOTOSYNTH,
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
    cell_work_upkeep,
    default_blueprint,
    food_energy,
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
    EYE: "зрительная клетка",
    PHOTOSYNTH: "фотосинтез",
    MUSCLE: "мышца",
}


def kind_help(kind: str) -> list[str]:
    """Короткие строки про выбранный вид: как работает, цена, голод, бой."""
    cost = cell_cost(kind)
    upkeep = cell_upkeep(kind)
    work = cell_work_upkeep(kind)
    food = food_energy(kind)
    chance = round(config.PHOTOSYNTH_UPKEEP_CHANCE * 100)
    return {
        SKIN: [
            "Мягкая клетка: гнётся, сминается и гасит удар.",
            "Растягиваться почти не может — щелей нет.",
            f"Цена {cost}. Аппетит {upkeep:g} за удар голода.",
            "Двигатель на длинной кожаной ножке толкает вяло.",
            f"Обломок даёт {food:g} энергии.",
        ],
        BONE: [
            "Твёрдый рычаг: не гнётся и не сминается,",
            "а мышца её ворочает.",
            "Соседние кости — один жёсткий кусок.",
            "Толчок двигателя передаёт целиком.",
            f"Цена {cost}. Не ест. Тяжёлая — разгон вялее.",
            "Выбить втрое труднее, сама пробивает",
            "даже при медленном сближении.",
            f"Обломок даёт {food:g} энергии.",
        ],
        THRUSTER: [
            "Толкает в сторону стрелки, пока держат цифру.",
            "На одну цифру можно повесить несколько.",
            f"Цена {cost}. Аппетит {upkeep:g}, до {work:g}",
            "если работал весь интервал голода.",
            f"Слабее вражеского. Держишь {config.THRUSTER_OVERHEAT_TIME:g} с —",
            f"пауза {config.THRUSTER_COOLDOWN_TIME:g} с, стержень краснеет.",
            "Короткий импульс, основной ход — плавники.",
            f"Обломок даёт {food:g} энергии.",
        ],
        PROCESSOR: [
            "Единственный способ съесть обломки:",
            "касанием они не подбираются.",
            f"Вплотную топит в {config.PROCESS_SPEEDUP:g} раз быстрее;",
            "несколько рядом складываются.",
            "Энергию забирает ближайший в зоне кольца.",
            "Сытому баку ничего не даёт.",
            f"Цена {cost}. В покое не ест, за работу — до {work:g}.",
            f"Обломок даёт {food:g} энергии.",
        ],
        EYE: [
            "Пока жива — расширяет обзор камеры в бою",
            "(несколько глаз складываются).",
            "Зрачок: еда, враг или сторона света.",
            f"Еду и врага дальше {config.EYE_SENSE_RANGE:g} клеток не видит.",
            f"Цена {cost}. Постоянно ест {upkeep:g}, работы нет.",
            f"Обломок даёт {food:g} энергии.",
        ],
        PHOTOSYNTH: [
            f"На каждом ударе голода даёт {config.PHOTOSYNTH_ENERGY_GAIN:g} энергии,",
            "еда для этого не нужна.",
            f"С шансом {chance}% сама просит 1, иначе 0.",
            f"Цена {cost}. Как кожа, но очень хрупкая —",
            "при ударе почти всегда вылетает первой.",
            f"Обломок даёт {food:g} энергии.",
        ],
        MUSCLE: [
            "Не клетка, а верёвка: пока держат цифру —",
            "стягивает концы, тело гнётся дугой.",
            "Отпустили — просто отпускает.",
            "Цена — по очку за клетку длины.",
            "Ест только пока работает",
            "(больше сила — больше аппетит).",
            "На кости — плавник или челюсть;",
            "внутри одного костяного куска бесполезна.",
            "Слишком сильная на тонком теле",
            "сперва упрётся, потом порвёт.",
        ],
    }.get(kind, [])

HELP_LINES = [
    "ЛКМ — поставить клетку",
    "ПКМ — убрать клетку",
    "Tab — сменить, что ставим",
    "Q, E или колесо — повернуть двигатель",
    "у глаза колесо — куда смотрит",
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
        self.look = LOOK_FOOD  # куда смотрит глаз, крутится колёсиком
        self.strength = 5  # сила мышцы, крутится колёсиком
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
                elif self.kind == EYE:
                    self._cycle_look(step)
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
                else:
                    self.direction = (self.direction - 1) % 6
            elif event.key in (pygame.K_e,):
                if self.kind == EYE:
                    self._cycle_look(1)
                else:
                    self.direction = (self.direction + 1) % 6
            elif pygame.K_1 <= event.key <= pygame.K_9:
                self.group = event.key - pygame.K_0
                if self.kind not in (THRUSTER, MUSCLE):
                    self.kind = THRUSTER
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._start_game()

    def _cycle_look(self, step: int) -> None:
        index = EYE_LOOKS.index(self.look)
        self.look = EYE_LOOKS[(index + step) % len(EYE_LOOKS)]

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
            elif self.kind == EYE:
                existing.look = self.look
            return
        if self.blueprint.cost() + cell_cost(self.kind) > config.CELL_BUDGET:
            return
        self.blueprint.place(CellSpec(coord, self.kind, self.direction, self.group, self.look))

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
            elif spec.kind == EYE:
                self._draw_eye_marks(surface, center, size, spec.look)

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
                f"Клеток: {len(self.blueprint)}",
                True,
                config.FG_COLOR,
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
                config.FG_COLOR,
            ),
            (x, y),
        )
        y += 28

        # без еды и без фотосинтеза тело только тратит — и умрёт с голоду
        kinds = {spec.kind for spec in self.blueprint.cells.values()}
        if PROCESSOR not in kinds and PHOTOSYNTH not in kinds:
            warn = (230, 130, 120)
            for line in (
                "Без переработчика или клеток фотосинтеза",
                "существо умрёт с голоду!",
            ):
                surface.blit(self.font.render(line, True, warn), (x, y))
                y += 26
        y += 8

        surface.blit(
            self.font.render(f"Ставим: {KIND_NAMES[self.kind]}", True, config.FG_COLOR), (x, y)
        )
        y += 26
        if self.kind == EYE:
            surface.blit(
                self.small_font.render(
                    f"Смотрит: {EYE_LOOK_NAMES[self.look]} (колесо / Q E)",
                    True,
                    config.FG_COLOR,
                ),
                (x, y),
            )
            y += 20
        if self.kind == MUSCLE:
            surface.blit(
                self.small_font.render(
                    f"Сила: {self.strength} (колесо)   кнопка: {self.group}",
                    True,
                    config.FG_COLOR,
                ),
                (x, y),
            )
            y += 20
        if self.kind == THRUSTER:
            surface.blit(
                self.small_font.render(
                    f"Кнопка двигателя: {self.group}", True, config.FG_COLOR
                ),
                (x, y),
            )
            y += 20
            surface.blit(self.small_font.render("Толкает сюда:", True, config.FG_COLOR), (x, y))
            self._draw_direction_preview(surface, (x + 190, y + 8))
            y += 40
        for line in kind_help(self.kind):
            surface.blit(self.small_font.render(line, True, config.FG_COLOR), (x, y))
            y += 20
        if self.kind == MUSCLE and self.muscle_start is not None:
            surface.blit(
                self.small_font.render("Теперь укажи второй конец", True, config.FOOD_COLOR),
                (x, y),
            )
            y += 20

        y += 8
        for line in HELP_LINES:
            surface.blit(self.small_font.render(line, True, config.FG_COLOR), (x, y))
            y += 20

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
