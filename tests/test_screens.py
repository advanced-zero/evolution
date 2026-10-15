"""Проверка перехода между экранами: редактор → бой → гибель → редактор."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from evolution import config, creature, saves, settings
from evolution.creature import ROOT, CellSpec, Species, default_blueprint
from evolution.i18n import STRINGS, t

# тест не должен затирать существо и настройки игрока
_test_dir = Path(tempfile.gettempdir()) / "evolution-test"
creature.SAVE_PATH = _test_dir / "creature.json"
saves.DATA_DIR = _test_dir
settings.SETTINGS_PATH = _test_dir / "settings.json"
settings.reset()
settings.save()


def _clear_saves() -> None:
    folder = saves.saves_dir()
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    for path in (creature.SAVE_PATH, saves.index_path()):
        if path.is_file():
            path.unlink()
    # пустой индекс, чтобы старый creature.json не подтянулся снова
    saves._write_index([], None)


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


def test_maneuver_wheel_and_digit_keys() -> None:
    _screen()
    from evolution.creature import MANEUVER
    from evolution.editor import EditorScene

    editor = EditorScene(default_blueprint())
    editor.kind = MANEUVER
    assert editor.brake == 10
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(0, 0), button=5))
    assert editor.brake == 9
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert editor.brake == 8
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_5))
    assert editor.kind == MANEUVER
    assert editor.group == 5


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
    # Esc ещё раз закрывает меню, не выходя в главное
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
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
    from evolution.scenes import MainMenuScene

    assert not editor.wants_quit
    assert isinstance(editor.update(1 / 60), MainMenuScene)

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


def test_main_menu_play_without_saves_opens_editor() -> None:
    screen = _screen()
    from evolution.editor import EditorScene
    from evolution.scenes import MainMenuScene

    _clear_saves()
    menu = MainMenuScene()
    menu.draw(screen)
    menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    next_scene = menu.update(1 / 60)
    assert isinstance(next_scene, EditorScene)
    assert next_scene.save_id is not None
    assert saves.list_saves()


def test_main_menu_play_with_save_opens_fight() -> None:
    screen = _screen()
    from evolution.scenes import MainMenuScene, PlayScene

    _clear_saves()
    saves.create_new()
    menu = MainMenuScene()
    menu.draw(screen)
    menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    next_scene = menu.update(1 / 60)
    assert isinstance(next_scene, PlayScene)


def test_saves_new_creature_opens_editor() -> None:
    screen = _screen()
    from evolution.editor import EditorScene
    from evolution.scenes import MainMenuScene

    _clear_saves()
    menu = MainMenuScene()
    menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert menu.page == "saves"
    menu.draw(screen)
    menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    next_scene = menu.update(1 / 60)
    assert isinstance(next_scene, EditorScene)
    assert len(saves.list_saves()) == 1


def test_editor_esc_menu_returns_to_main() -> None:
    screen = _screen()
    from evolution.editor import EditorScene
    from evolution.scenes import MainMenuScene

    editor = EditorScene(default_blueprint())
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    editor.draw(screen)
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    next_scene = editor.update(1 / 60)
    assert isinstance(next_scene, MainMenuScene)


def _move(editor, pos: tuple[float, float]) -> None:
    editor.handle_event(
        pygame.event.Event(
            pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)
        )
    )


def test_editor_hud_gap_allows_grid_click() -> None:
    screen = _screen()
    from evolution.editor import EditorScene

    editor = EditorScene(default_blueprint())
    editor.draw(screen)
    gap = (config.WIDTH - 80, config.HEIGHT // 2)
    assert not editor._over_hud(gap)
    stats = editor._hud_hit[0]
    click = (stats.centerx, stats.bottom - 16)
    assert editor._over_hud(click)
    before = len(editor.blueprint)
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=click, button=1))
    assert len(editor.blueprint) == before


def test_editor_help_follows_hex_and_slides_away() -> None:
    screen = _screen()
    from evolution.editor import ORIGIN, EditorScene

    editor = EditorScene(default_blueprint())
    editor.draw(screen)
    _move(editor, ORIGIN)
    editor.update(config.EDITOR_HELP_SLIDE_TIME + 0.05)
    assert editor._help_slide == 1.0
    kind, spec = editor._inspect_help()
    assert kind == "root"
    assert spec is not None

    empty = (ORIGIN[0] + 220, ORIGIN[1] + 220)
    _move(editor, empty)
    assert editor._inspect_help() == (editor.kind, None)

    keys = editor._hud_hit[1]
    _move(editor, keys.center)
    editor.update(config.EDITOR_HELP_HIDE_DELAY + config.EDITOR_HELP_SLIDE_TIME + 0.05)
    assert editor._help_slide == 0.0
    editor.draw(screen)


def test_legacy_creature_json_migrates() -> None:
    _clear_saves()
    saves.index_path().unlink()
    Species([default_blueprint()]).save(creature.SAVE_PATH)
    listed = saves.list_saves()
    assert len(listed) == 1
    loaded = saves.load_current()
    assert loaded is not None
    assert ROOT in loaded.stages[0].cells


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"ok  {name}")
    print("Экраны в порядке.")
