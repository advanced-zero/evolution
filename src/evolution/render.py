"""Отрисовка: шестиугольники, существа, еда, фон."""

from __future__ import annotations

import math

import pygame

from evolution import config, hexgrid
from evolution.creature import THRUSTER, Creature, cell_color
from evolution.world import Food, World


def get_font(size: int, bold: bool = False) -> pygame.font.Font:
    """Шрифт с поддержкой кириллицы (со стандартным запасным вариантом)."""
    return pygame.font.SysFont(
        "dejavusans,notosans,liberationsans,freesans,arial", size, bold=bold
    )


def draw_hex(
    surface: pygame.Surface,
    center: tuple[float, float],
    size: float,
    color: tuple[int, int, int],
    angle: float = 0.0,
    width: int = 0,
) -> None:
    points = hexgrid.corners(center[0], center[1], size, angle)
    if width == 0:
        pygame.draw.polygon(surface, color, points)
        pygame.draw.polygon(surface, config.OUTLINE_COLOR, points, 1)
    else:
        pygame.draw.polygon(surface, color, points, width)


def draw_background(surface: pygame.Surface, camera: tuple[float, float]) -> None:
    """Точки на фоне, чтобы было видно движение, и рамка мира."""
    surface.fill(config.BG_COLOR)
    step = 100
    cx, cy = camera
    start_x = int(cx // step * step)
    start_y = int(cy // step * step)
    for x in range(start_x, int(cx) + config.WIDTH + step, step):
        for y in range(start_y, int(cy) + config.HEIGHT + step, step):
            if 0 <= x <= config.WORLD_WIDTH and 0 <= y <= config.WORLD_HEIGHT:
                surface.fill(config.GRID_COLOR, (x - cx, y - cy, 2, 2))

    border = pygame.Rect(-cx, -cy, config.WORLD_WIDTH, config.WORLD_HEIGHT)
    pygame.draw.rect(surface, config.BORDER_COLOR, border, 3)


def draw_creature(
    surface: pygame.Surface,
    creature: Creature,
    camera: tuple[float, float],
    active_groups: set[int] | None = None,
    font: pygame.font.Font | None = None,
) -> None:
    cx, cy = camera
    active_groups = active_groups or set()

    for coord in creature.alive_cells:
        spec = creature.blueprint.cells[coord]
        wx, wy = creature.cell_world_pos(coord)
        sx, sy = wx - cx, wy - cy
        if not (-40 <= sx <= config.WIDTH + 40 and -40 <= sy <= config.HEIGHT + 40):
            continue

        color = cell_color(coord, spec, creature.is_player)
        draw_hex(surface, (sx, sy), config.HEX_SIZE, color, creature.angle)

        if spec.kind == THRUSTER:
            dx, dy = hexgrid.direction_vector(spec.direction)
            a = creature.angle
            wdx = dx * math.cos(a) - dy * math.sin(a)
            wdy = dx * math.sin(a) + dy * math.cos(a)
            tip = (sx + wdx * config.HEX_SIZE * 0.9, sy + wdy * config.HEX_SIZE * 0.9)
            pygame.draw.line(surface, config.OUTLINE_COLOR, (sx, sy), tip, 2)
            if spec.group in active_groups:
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


def camera_for(world: World) -> tuple[float, float]:
    """Левый верхний угол камеры: держим игрока в центре, но не вылезаем из мира."""
    cx = world.player.x - config.WIDTH / 2.0
    cy = world.player.y - config.HEIGHT / 2.0
    cx = min(max(cx, -20.0), config.WORLD_WIDTH - config.WIDTH + 20.0)
    cy = min(max(cy, -20.0), config.WORLD_HEIGHT - config.HEIGHT + 20.0)
    return cx, cy
