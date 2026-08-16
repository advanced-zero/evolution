"""Водный фон: пятна мути, планктон, пузырьки и темнота за краем мира.

Вид сверху, поэтому «глубины сверху вниз» нет: море разное не по высоте, а по
месту. Карта воды считается один раз и лежит в кэше модуля; всё, что движется,
— чистая функция времени, никакого своего состояния у фона нет.
"""

from __future__ import annotations

import math
import random

import pygame

from evolution import config


# --- шум ---


def _fade(t: float) -> float:
    """Сглаживание, чтобы пятна перетекали друг в друга без углов."""
    return t * t * (3.0 - 2.0 * t)


def _grid(rng: random.Random, cols: int, rows: int) -> list[list[float]]:
    return [[rng.random() for _ in range(cols + 1)] for _ in range(rows + 1)]


def _sample(grid: list[list[float]], x: float, y: float) -> float:
    """Значение шума между узлами сетки (x, y — в узлах, не в пикселях)."""
    x0 = min(max(int(x), 0), len(grid[0]) - 2)
    y0 = min(max(int(y), 0), len(grid) - 2)
    tx = _fade(min(max(x - x0, 0.0), 1.0))
    ty = _fade(min(max(y - y0, 0.0), 1.0))
    top = grid[y0][x0] + (grid[y0][x0 + 1] - grid[y0][x0]) * tx
    bottom = grid[y0 + 1][x0] + (grid[y0 + 1][x0 + 1] - grid[y0 + 1][x0]) * tx
    return top + (bottom - top) * ty


def _hash01(a: int, b: int, salt: int) -> float:
    """Случайное число из номеров — чтобы пузырьки не хранили своё состояние."""
    h = (a * 374761393 + b * 668265263 + salt * 2654435761) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 0xFFFFFFFF


def _caustic_tile(rng: random.Random, zoom: float) -> pygame.Surface:
    """Плитка солнечной паутины: светлые нити по границам ячеек.

    Считаем расстояние до двух ближайших точек: у границы между ячейками они
    почти равны — там и загорается нить. Точки заворачиваются по краям плитки,
    поэтому плитка стыкуется сама с собой без швов.
    """
    size = config.WATER_CAUSTIC_TILE
    cells = config.WATER_CAUSTIC_CELLS
    step = size / cells
    points = [
        [
            (
                (cx + rng.random()) * step,
                (cy + rng.random()) * step,
            )
            for cx in range(cells)
        ]
        for cy in range(cells)
    ]

    tile = pygame.Surface((size, size))
    width = config.WATER_CAUSTIC_WIDTH * step
    for py in range(size):
        cy = int(py / step)
        for px in range(size):
            cx = int(px / step)
            first = second = float("inf")
            for oy in range(-1, 2):
                row = points[(cy + oy) % cells]
                shift_y = ((cy + oy) // cells) * size
                for ox in range(-1, 2):
                    qx, qy = row[(cx + ox) % cells]
                    qx += ((cx + ox) // cells) * size
                    qy += shift_y
                    d = (qx - px) ** 2 + (qy - py) ** 2
                    if d < first:
                        first, second = d, first
                    elif d < second:
                        second = d
            edge = math.sqrt(second) - math.sqrt(first)
            glow = max(0.0, 1.0 - edge / width) ** 2
            level = int(config.WATER_CAUSTIC_BRIGHT * glow)
            tile.set_at((px, py), (level, level, level))

    span = int(size * zoom)
    return pygame.transform.smoothscale(tile, (span, span))


def _mix(
    dark: tuple[int, int, int], light: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    t = min(max(t, 0.0), 1.0)
    return (
        int(dark[0] + (light[0] - dark[0]) * t),
        int(dark[1] + (light[1] - dark[1]) * t),
        int(dark[2] + (light[2] - dark[2]) * t),
    )


# --- заготовки, которые считаются один раз ---


class _Water:
    """Всё, что дорого построить: карта моря, спрайты и раскладка частиц."""

    def __init__(self) -> None:
        rng = random.Random(config.WATER_SEED)
        self.map = self._build_map(rng)
        self.lively = self._build_lively(rng)
        self.shimmers = self._build_shimmers(rng)
        self.shimmer_sprites = self._build_shimmer_sprites()
        self.motes = self._build_motes(rng)
        self.bubbles = self._build_bubbles(rng)
        self.edges = self._build_edges()
        self.dim = pygame.Surface((config.WIDTH, config.HEIGHT))
        self.dim.fill(config.WATER_VOID_COLOR)
        self.dim.set_alpha(config.WATER_CALM_DIM)
        self.bubble_buf = pygame.Surface(
            (int(config.WATER_BUBBLE_SIZE * 2 + 6),) * 2, pygame.SRCALPHA
        )

    # карта моря: три октавы шума, растянутые на весь мир
    def _build_map(self, rng: random.Random) -> pygame.Surface:
        cell = config.WATER_CELL
        cols = max(2, int(config.WORLD_WIDTH / cell) + 1)
        rows = max(2, int(config.WORLD_HEIGHT / cell) + 1)

        field = [[0.0] * cols for _ in range(rows)]
        total = 0.0
        # Дробные множители и сдвиг у каждой октавы — чтобы их сетки не совпали
        # углами: иначе на воде проступает квадратная решётка.
        for weight, scale in ((1.0, 1.0), (0.5, 2.17), (0.25, 4.63)):
            size = config.WATER_PATCH_SIZE / scale
            ox, oy = rng.random(), rng.random()
            grid = _grid(
                rng,
                max(1, int(config.WORLD_WIDTH / size) + 2),
                max(1, int(config.WORLD_HEIGHT / size) + 2),
            )
            for fy in range(rows):
                wy = (fy + 0.5) * cell / size + oy
                row = field[fy]
                for fx in range(cols):
                    row[fx] += _sample(grid, (fx + 0.5) * cell / size + ox, wy) * weight
            total += weight

        small = pygame.Surface((cols, rows))
        for fy in range(rows):
            for fx in range(cols):
                # растягиваем разброс: без этого шум жмётся к середине и море
                # получается однотонным — как раз то, чего не хотели
                v = (field[fy][fx] / total - 0.5) * 1.8 + 0.5
                small.set_at(
                    (fx, fy),
                    _mix(config.WATER_DEEP_COLOR, config.WATER_SHALLOW_COLOR, v),
                )

        # Растягиваем удвоениями, а не одним рывком: за один раз растяжка в 40
        # раз оставляет на воде заметные квадраты, а по шагам они сглаживаются.
        big = small
        while big.get_width() * 2 < config.WORLD_WIDTH:
            big = pygame.transform.smoothscale(
                big, (big.get_width() * 2, big.get_height() * 2)
            )
        big = pygame.transform.smoothscale(big, (config.WORLD_WIDTH, config.WORLD_HEIGHT))
        self._bake_caustics(big, rng)
        return big.convert() if pygame.display.get_init() else big

    def _bake_caustics(self, sea: pygame.Surface, rng: random.Random) -> None:
        """Вклеивает в карту солнечную паутину — сразу, а не каждый кадр.

        Сетка привязана к месту: когда плывёшь, она проезжает мимо, как в воде.
        Умножение на саму воду гасит нити на глубине и разжигает на отмелях.
        """
        layer = pygame.Surface(sea.get_size())
        # два слоя разного размера: одна плитка на весь мир читалась бы как
        # повторяющиеся обои, а вдвоём они сбивают этот повтор
        for zoom in config.WATER_CAUSTIC_ZOOM:
            tile = _caustic_tile(rng, zoom)
            span = tile.get_width()
            for y in range(0, sea.get_height(), span):
                for x in range(0, sea.get_width(), span):
                    layer.blit(tile, (x, y), special_flags=pygame.BLEND_RGB_ADD)
        layer.blit(sea, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        sea.blit(layer, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    # где вода шевелится, а где стоит — своё, независимое от цвета поле
    def _build_lively(self, rng: random.Random) -> list[list[float]]:
        size = config.WATER_PATCH_SIZE * 1.4
        return _grid(
            rng,
            max(1, int(config.WORLD_WIDTH / size) + 1),
            max(1, int(config.WORLD_HEIGHT / size) + 1),
        )

    def liveliness(self, wx: float, wy: float) -> float:
        size = config.WATER_PATCH_SIZE * 1.4
        return _sample(self.lively, wx / size, wy / size)

    # мягкие пятна света стоят по сетке, но только в «живых» местах
    def _build_shimmers(self, rng: random.Random) -> list[tuple[float, float, int, float]]:
        step = config.WATER_SHIMMER_STEP
        spots: list[tuple[float, float, int, float]] = []
        y = step * 0.5
        while y < config.WORLD_HEIGHT:
            x = step * 0.5
            while x < config.WORLD_WIDTH:
                wx = x + rng.uniform(-step * 0.4, step * 0.4)
                wy = y + rng.uniform(-step * 0.4, step * 0.4)
                if self.liveliness(wx, wy) > config.WATER_LIVELY_LEVEL:
                    spots.append((wx, wy, rng.randrange(3), rng.uniform(0.0, math.tau)))
                x += step
            y += step
        return spots

    def _build_shimmer_sprites(self) -> list[pygame.Surface]:
        radius = int(config.WATER_SHIMMER_SIZE)
        base = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        color = config.WATER_SHALLOW_COLOR
        # кольцами от края к центру: получается мягкое пятно без резкой границы
        for i in range(radius, 0, -2):
            t = 1.0 - i / radius
            alpha = int(255 * t * t)
            pygame.draw.circle(base, (*color, alpha), (radius, radius), i)
        return [
            pygame.transform.smoothscale(base, (int(radius * 2 * k),) * 2)
            for k in (0.6, 0.85, 1.0)
        ]

    # планктон ходит стайками; плитка 2×2 экрана повторяется по модулю
    def _build_motes(
        self, rng: random.Random
    ) -> list[tuple[float, float, float, float, tuple[int, int, int], int, float]]:
        tw, th = config.WIDTH * 2, config.HEIGHT * 2
        drift = config.WATER_MOTE_DRIFT
        low, high = config.WATER_SCHOOL_SIZE
        spread = config.WATER_SCHOOL_RADIUS
        motes = []
        while len(motes) < config.WATER_MOTE_COUNT:
            # стайку сносит целиком: своя скорость только чуть-чуть разная,
            # иначе крупинки разбредутся и никакой стайки не выйдет
            cx, cy = rng.uniform(0.0, tw), rng.uniform(0.0, th)
            vx, vy = rng.uniform(-drift, drift), rng.uniform(-drift, drift)
            for _ in range(rng.randint(low, high)):
                shade = rng.uniform(0.3, 1.0)
                # к середине стайки крупинки жмутся плотнее
                r = spread * rng.random() ** 1.6
                a = rng.uniform(0.0, math.tau)
                motes.append(
                    (
                        cx + math.cos(a) * r,
                        cy + math.sin(a) * r,
                        vx + rng.uniform(-0.4, 0.4),
                        vy + rng.uniform(-0.4, 0.4),
                        tuple(int(c * shade) for c in config.WATER_MOTE_COLOR),
                        1 if shade < 0.7 else 2,
                        rng.uniform(0.0, math.tau),
                    )
                )
        return motes

    def _build_bubbles(self, rng: random.Random) -> list[tuple[float, float]]:
        return [
            (
                rng.uniform(config.WATER_BUBBLE_PERIOD_MIN, config.WATER_BUBBLE_PERIOD_MAX),
                rng.random(),
            )
            for _ in range(config.WATER_BUBBLE_COUNT)
        ]

    # полосы, которыми вода у края мира уходит в черноту
    def _build_edges(self) -> tuple[pygame.Surface, pygame.Surface]:
        fade = max(2, int(config.WATER_EDGE_FADE))
        strip = pygame.Surface((fade, 1), pygame.SRCALPHA)
        for i in range(fade):
            t = i / (fade - 1)
            strip.set_at((i, 0), (*config.WATER_VOID_COLOR, int(255 * (1.0 - t) ** 1.6)))
        side = pygame.transform.smoothscale(strip, (fade, config.HEIGHT))
        top = pygame.transform.smoothscale(
            pygame.transform.rotate(strip, -90), (config.WIDTH, fade)
        )
        return side, top


_cache: _Water | None = None


def prepare() -> _Water:
    """Строит карту воды при первом обращении и дальше отдаёт готовую."""
    global _cache
    if _cache is None:
        _cache = _Water()
    return _cache


# --- отрисовка кадра ---


def draw(
    surface: pygame.Surface,
    camera: tuple[float, float],
    time: float,
    calm: bool = False,
) -> None:
    """Рисует воду под всем остальным. `calm` — тихий вариант для редактора."""
    water = prepare()
    cx, cy = camera
    surface.fill(config.WATER_VOID_COLOR)

    visible = pygame.Rect(int(cx), int(cy), config.WIDTH, config.HEIGHT).clip(
        water.map.get_rect()
    )
    if visible.width > 0 and visible.height > 0:
        surface.blit(water.map, (visible.x - cx, visible.y - cy), visible)

    if calm:
        surface.blit(water.dim, (0, 0))
    else:
        _draw_shimmer(surface, water, cx, cy, time)

    _draw_motes(surface, water, cx, cy, time, calm)

    if not calm:
        _draw_bubbles(surface, water, cx, cy, time)

    _draw_edges(surface, water, cx, cy)


def _draw_shimmer(
    surface: pygame.Surface, water: _Water, cx: float, cy: float, time: float
) -> None:
    """Пятна света тихо дышат — только там, где вода живая."""
    for wx, wy, size, phase in water.shimmers:
        sprite = water.shimmer_sprites[size]
        half = sprite.get_width() * 0.5
        sx, sy = wx - cx - half, wy - cy - half
        if not (-half * 2 < sx < config.WIDTH and -half * 2 < sy < config.HEIGHT):
            continue
        breath = 0.5 + 0.5 * math.sin(time * math.tau / config.WATER_SHIMMER_PERIOD + phase)
        sprite.set_alpha(int(config.WATER_SHIMMER_ALPHA * (0.35 + 0.65 * breath)))
        surface.blit(sprite, (sx, sy))


def _draw_motes(
    surface: pygame.Surface, water: _Water, cx: float, cy: float, time: float, calm: bool
) -> None:
    """Стайки взвеси: по ним видно, что плывёшь."""
    tw, th = config.WIDTH * 2, config.HEIGHT * 2
    wobble = config.WATER_MOTE_WOBBLE
    count = len(water.motes)
    if calm:
        count = int(count * config.WATER_CALM_MOTES)
    for x0, y0, vx, vy, color, size, phase in water.motes[:count]:
        # крупинка ещё и покачивается на месте — стайка выглядит живой
        sx = (x0 + vx * time + math.sin(time * 0.9 + phase) * wobble - cx) % tw
        sy = (y0 + vy * time + math.cos(time * 0.7 + phase) * wobble - cy) % th
        if sx < config.WIDTH and sy < config.HEIGHT:
            surface.fill(color, (sx, sy, size, size))


def _draw_bubbles(
    surface: pygame.Surface, water: _Water, cx: float, cy: float, time: float
) -> None:
    """Вид сверху: пузырёк не всплывает вверх экрана, а растёт и тает."""
    tw, th = config.WIDTH * 2, config.HEIGHT * 2
    buf = water.bubble_buf
    half = buf.get_width() * 0.5
    for slot, (period, phase) in enumerate(water.bubbles):
        turns = time / period + phase
        cycle = int(turns)
        life = turns - cycle
        sx = (_hash01(slot, cycle, 1) * tw - cx) % tw
        sy = (_hash01(slot, cycle, 2) * th - cy) % th
        if sx >= config.WIDTH or sy >= config.HEIGHT:
            continue
        if water.liveliness(cx + sx, cy + sy) <= config.WATER_LIVELY_LEVEL:
            continue

        radius = config.WATER_BUBBLE_SIZE * math.sqrt(life)
        alpha = int(190 * min(1.0, life * 5.0) * (1.0 - life) ** 1.5)
        if radius < 1.0 or alpha <= 0:
            continue
        buf.fill((0, 0, 0, 0))
        pygame.draw.circle(
            buf, (*config.WATER_BUBBLE_COLOR, alpha), (half, half), radius, 1
        )
        surface.blit(buf, (sx - half, sy - half))


def _draw_edges(surface: pygame.Surface, water: _Water, cx: float, cy: float) -> None:
    """За краем мира — чернота, рамки нет."""
    side, top = water.edges
    fade = side.get_width()
    surface.blit(side, (-cx, 0))
    surface.blit(pygame.transform.flip(side, True, False), (config.WORLD_WIDTH - fade - cx, 0))
    surface.blit(top, (0, -cy))
    surface.blit(
        pygame.transform.flip(top, False, True), (0, config.WORLD_HEIGHT - top.get_height() - cy)
    )
