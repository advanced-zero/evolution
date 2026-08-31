"""Проверка перехода между экранами: редактор → бой → гибель → редактор."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from evolution import config, creature, settings
from evolution.creature import ROOT, CellSpec, Species, default_blueprint
from evolution.i18n import STRINGS, t

# тест не должен затирать существо и настройки игрока
_test_dir = Path(tempfile.gettempdir()) / "evolution-test"
creature.SAVE_PATH = _test_dir / "creature.json"
settings.SETTINGS_PATH = _test_dir / "settings.json"
settings.reset()
settings.save()


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


def test_editor_stages_save_and_start_from_first() -> None:
    screen = _screen()
    from evolution.editor import EditorScene
    from evolution.scenes import PlayScene

    baby = default_blueprint()
    grown = baby.copy()
    grown.place(CellSpec((2, 0), "skin"))
    editor = EditorScene(Species([baby, grown]))
    assert len(editor.species.stages) == 2
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHTBRACKET))
    assert editor.stage_index == 1
    editor.draw(screen)
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    play = editor.update(1 / 60)
    assert isinstance(play, PlayScene)
    assert play.world.player.stage_index == 0
    assert len(play.world.player.species.stages) == 2
    saved = Species.load(creature.SAVE_PATH)
    assert saved is not None and len(saved.stages) == 2


def test_esc_menu_pauses_and_returns_to_editor() -> None:
    screen = _screen()
    from evolution.editor import EditorScene
    from evolution.scenes import PlayScene

    editor = EditorScene(default_blueprint())
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert editor.menu.open
    editor.draw(screen)
    # в редакторе «в редактор» просто закрывает меню
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert not editor.menu.open

    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    play = editor.update(1 / 60)
    assert isinstance(play, PlayScene)

    play.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert play.menu.open
    frozen = play.world.time
    play.update(1 / 60)
    assert play.world.time == frozen
    play.draw(screen)

    play.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    play.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    back = play.update(1 / 60)
    assert isinstance(back, EditorScene)


def test_menu_quit_and_language() -> None:
    screen = _screen()
    from evolution.editor import EditorScene

    settings.reset()
    editor = EditorScene(default_blueprint())
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert editor.wants_quit

    editor = EditorScene(default_blueprint())
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    editor.draw(screen)
    assert editor.menu.page == "options"
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert settings.language == "en"
    assert t("menu.title") == "Menu"
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert editor.menu.page == "root"
    settings.reset()


def test_i18n_keys_match() -> None:
    assert set(STRINGS["ru"]) == set(STRINGS["en"])


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"ok  {name}")
    print("Экраны в порядке.")
