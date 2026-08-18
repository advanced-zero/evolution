"""Отрисовка: шестиугольники, существа, еда, фон."""

from __future__ import annotations

import math

import pygame

from evolution import config, hexgrid, water
from evolution.creature import EYE, PROCESSOR, THRUSTER, Creature, cell_color
from evolution.world import Food, World


def get_font(size: int, bold: bool = False) -> pygame.font.Font:
    """Шрифт с поддержкой кириллицы (со стандартным запасным вариантом)."""
    return pygame.font.SysFont(
        "dejavusans,notosans,liberationsans,freesans,arial", size, bold=bold
    )


def squashed_corners(
    center: tuple[float, float],
    size: float,
    angle: float,
    squeeze: float,
    squeeze_angle: float,
) -> list[tuple[float, float]]:
    """Углы деформированной клетки.

    Смяло (`squeeze` > 0) — клетка плющится вдоль оси и раздаётся поперёк;
    растянуло (`squeeze` < 0) — наоборот вытягивается, закрывая собой щель
    между разъехавшимися соседями.
    """
    cx, cy = center
    cos_a, sin_a = math.cos(squeeze_angle), math.sin(squeeze_angle)
    along = 1.0 - squeeze
    across = 1.0 + squeeze * config.SOFT_BULGE
    points = []
    for px, py in hexgrid.corners(0.0, 0.0, size, angle):
        # переводим в оси сжатия, плющим и возвращаем обратно
        u = px * cos_a + py * sin_a
        v = -px * sin_a + py * cos_a
        u *= along
        v *= across
        points.append((cx + u * cos_a - v * sin_a, cy + u * sin_a + v * cos_a))
    return points


def draw_hex(
    surface: pygame.Surface,
    center: tuple[float, float],
    size: float,
    color: tuple[int, int, int],
    angle: float = 0.0,
    width: int = 0,
    squeeze: float = 0.0,
    squeeze_angle: float = 0.0,
) -> None:
    if abs(squeeze) > 0.01:
        points = squashed_corners(center, size, angle, squeeze, squeeze_angle)
    else:
        points = hexgrid.corners(center[0], center[1], size, angle)
    if width == 0:
        pygame.draw.polygon(surface, color, points)
        pygame.draw.polygon(surface, config.OUTLINE_COLOR, points, 1)
    else:
        pygame.draw.polygon(surface, color, points, width)


def draw_background(
    surface: pygame.Surface,
    camera: tuple[float, float],
    time: float = 0.0,
    calm: bool = False,
) -> None:
    """Водный фон: пятна мути, планктон, пузырьки и темнота за краем мира."""
    water.draw(surface, camera, time, calm)


def draw_creature(
    surface: pygame.Surface,
    creature: Creature,
    camera: tuple[float, float],
    active_groups: set[int] | None = None,
    font: pygame.font.Font | None = None,
) -> None:
    cx, cy = camera
    active_groups = active_groups or set()

    # мышцы рисуем под клетками: работающая натянута и ярче
    muscle_color = config.MUSCLE_COLOR if creature.is_player else config.ENEMY_MUSCLE_COLOR
    for index, muscle in creature.muscles_alive():
        ax, ay = creature.cell_world_pos(muscle.a)
        bx, by = creature.cell_world_pos(muscle.b)
        working = index in creature.pulling
        color = muscle_color if working else tuple(c // 2 for c in muscle_color)
        pygame.draw.line(
            surface,
            color,
            (ax - cx, ay - cy),
            (bx - cx, by - cy),
            (3 if working else 1) + muscle.strength // 4,
        )

    # пока переработчик топит обломок, видно, откуда он снимет энергию
    for coord in creature.processing:
        wx, wy = creature.cell_world_pos(coord)
        pygame.draw.circle(
            surface,
            config.PROCESSOR_COLOR if creature.is_player else config.ENEMY_PROCESSOR_COLOR,
            (int(wx - cx), int(wy - cy)),
            int(config.COLLECT_RADIUS),
            1,
        )

    for coord in creature.alive_cells:
        spec = creature.blueprint.cells[coord]
        wx, wy = creature.cell_world_pos(coord)
        sx, sy = wx - cx, wy - cy
        if not (-40 <= sx <= config.WIDTH + 40 and -40 <= sy <= config.HEIGHT + 40):
            continue

        color = cell_color(coord, spec, creature.is_player)
        # согнутая клетка ещё и доворачивается, а смятая — плющится
        a = creature.render_angle(coord)
        squeeze, squeeze_angle = creature.squeeze.get(coord, (0.0, 0.0))
        draw_hex(
            surface,
            (sx, sy),
            config.HEX_SIZE,
            color,
            a,
            squeeze=squeeze,
            squeeze_angle=squeeze_angle + creature.angle,
        )

        if spec.kind == PROCESSOR:
            # «пасть»: тёмное кольцо в центре, чтобы отличать от кожи
            pygame.draw.circle(
                surface, config.OUTLINE_COLOR, (int(sx), int(sy)), int(config.HEX_SIZE * 0.45), 2
            )

        if spec.kind == EYE:
            # «зрачок» в центре, чтобы отличать от кожи
            pygame.draw.circle(
                surface, config.OUTLINE_COLOR, (int(sx), int(sy)), int(config.HEX_SIZE * 0.3)
            )

        if spec.kind == THRUSTER:
            dx, dy = hexgrid.direction_vector(spec.direction)
            wdx = dx * math.cos(a) - dy * math.sin(a)
            wdy = dx * math.sin(a) + dy * math.cos(a)
            tip = (sx + wdx * config.HEX_SIZE * 0.9, sy + wdy * config.HEX_SIZE * 0.9)
            overheated = creature.thruster_cooldown.get(spec.group, 0.0) > 0.0
            stick_color = config.ENERGY_LOW_COLOR if overheated else config.OUTLINE_COLOR
            pygame.draw.line(surface, stick_color, (sx, sy), tip, 2)
            if spec.group in active_groups and not overheated:
                # «выхлоп» бьёт назад
                flame = (sx - wdx * config.HEX_SIZE * 1.8, sy - wdy * config.HEX_SIZE * 1.8)
                pygame.draw.line(surface, config.FLAME_COLOR, (sx, sy), flame, 3)
            if font is not None and creature.is_player:
                label = font.render(str(spec.group), True, config.OUTLINE_COLOR)
                surface.blit(label, label.get_rect(center=(sx, sy)))


def draw_food(surface: pygame.Surface, food: Food, camera: tuple[float, float]) -> None:
    """Обломок выглядит как клетка, которой он был, — только гаснет со временем."""
    sx, sy = food.x - camera[0], food.y - camera[1]
    if not (-40 <= sx <= config.WIDTH + 40 and -40 <= sy <= config.HEIGHT + 40):
        return
    fade = min(1.0, max(0.25, food.life / config.FOOD_FADE_TIME))
    color = tuple(int(c * fade) for c in food.color)
    draw_hex(surface, (sx, sy), config.HEX_SIZE, color, food.angle)

    if food.kind == THRUSTER:
        dx, dy = hexgrid.direction_vector(food.direction)
        wdx = dx * math.cos(food.angle) - dy * math.sin(food.angle)
        wdy = dx * math.sin(food.angle) + dy * math.cos(food.angle)
        tip = (sx + wdx * config.HEX_SIZE * 0.9, sy + wdy * config.HEX_SIZE * 0.9)
        pygame.draw.line(surface, config.OUTLINE_COLOR, (sx, sy), tip, 2)


def draw_energy_bar(
    surface: pygame.Surface,
    rect: tuple[int, int, int, int],
    value: float,
    maximum: float,
) -> None:
    """Полоска энергии: на голодном баке краснеет."""
    x, y, w, h = rect
    share = 0.0 if maximum <= 0.0 else min(1.0, max(0.0, value / maximum))
    pygame.draw.rect(surface, config.GRID_COLOR, rect)
    color = config.ENERGY_COLOR if share > 0.25 else config.ENERGY_LOW_COLOR
    if share > 0.0:
        pygame.draw.rect(surface, color, (x, y, max(2, int(w * share)), h))
    pygame.draw.rect(surface, config.BORDER_COLOR, rect, 1)


def camera_for(world: World) -> tuple[float, float]:
    """Левый верхний угол камеры: держим игрока в центре, но не вылезаем из мира."""
    cx = world.player.x - config.WIDTH / 2.0
    cy = world.player.y - config.HEIGHT / 2.0
    cx = min(max(cx, -20.0), config.WORLD_WIDTH - config.WIDTH + 20.0)
    cy = min(max(cy, -20.0), config.WORLD_HEIGHT - config.HEIGHT + 20.0)
    return cx, cy


def calm_camera(time: float) -> tuple[float, float]:
    """Камера для экранов без мира: тихо дрейфует где-то посреди моря."""
    cx = config.WORLD_WIDTH * 0.5 - config.WIDTH / 2.0 + math.cos(time * 0.05) * 140.0
    cy = config.WORLD_HEIGHT * 0.5 - config.HEIGHT / 2.0 + math.sin(time * 0.04) * 100.0
    return cx, cy
