"""Проверка перехода между экранами: редактор → бой → гибель → редактор."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from evolution import config, creature
from evolution.creature import ROOT, default_blueprint

# тест не должен затирать существо, которое собрал игрок
creature.SAVE_PATH = Path(tempfile.gettempdir()) / "evolution-test" / "creature.json"


def _screen() -> pygame.Surface:
    pygame.init()
    return pygame.display.set_mode((config.WIDTH, config.HEIGHT))


def test_full_loop() -> None:
    screen = _screen()
    from evolution.editor import ORIGIN, EditorScene
    from evolution.scenes import GameOverScene, PlayScene

    editor = EditorScene(default_blueprint())
    before = len(editor.blueprint)
    # ставим клетку кожи справа от центра
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    spot = (ORIGIN[0] + config.EDITOR_HEX_SIZE * 1.8, ORIGIN[1] + config.EDITOR_HEX_SIZE * 1.6)
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=spot, button=1))
    assert len(editor.blueprint) == before + 1
    editor.draw(screen)

    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    play = editor.update(1 / 60)
    assert isinstance(play, PlayScene)

    play.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1))
    assert play.active_groups == {1}
    for _ in range(120):
        play.update(1 / 60)
    play.draw(screen)
    play.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_1))
    assert play.active_groups == set()

    # добиваем существо и ждём экран гибели
    play.world.drop_food(play.world.player, play.world.player.remove_cell(ROOT))
    over = None
    for _ in range(120):
        over = play.update(1 / 60) or over
    assert isinstance(over, GameOverScene)
    over.draw(screen)

    over.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    again = over.update(1 / 60)
    assert isinstance(again, EditorScene)
    again.draw(screen)


def test_water_draws_anywhere() -> None:
    """Фон рисуется в любой точке мира и в любой момент времени."""
    screen = _screen()
    from evolution import water

    first = water.prepare()
    assert water.prepare() is first, "карта воды должна строиться один раз"

    corners = [
        (-config.WIDTH, -config.HEIGHT),  # камера целиком за краем мира
        (-20.0, -20.0),
        (config.WORLD_WIDTH / 2, config.WORLD_HEIGHT / 2),
        (config.WORLD_WIDTH, config.WORLD_HEIGHT),
    ]
    for camera in corners:
        for moment in (0.0, 40.0):
            water.draw(screen, camera, moment)
            water.draw(screen, camera, moment, calm=True)


def test_eye_wheel_cycles_look() -> None:
    _screen()
    from evolution.creature import EYE, EYE_LOOKS, LOOK_ENEMY, LOOK_FOOD
    from evolution.editor import EditorScene

    editor = EditorScene(default_blueprint())
    editor.kind = EYE
    assert editor.look == LOOK_FOOD
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(0, 0), button=4))
    assert editor.look == LOOK_ENEMY
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert editor.look == LOOK_FOOD
    for _ in range(len(EYE_LOOKS)):
        editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(0, 0), button=4))
    assert editor.look == LOOK_FOOD


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"ok  {name}")
    print("Экраны в порядке.")
