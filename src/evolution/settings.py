"""Язык и окно: читаются с диска и сразу применяются."""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from evolution import config

SETTINGS_PATH = Path.home() / ".local" / "share" / "evolution" / "settings.json"

LANG_RU = "ru"
LANG_EN = "en"
LANGUAGES = (LANG_RU, LANG_EN)

language: str = LANG_RU
fullscreen: bool = False


def reset() -> None:
    """Значения по умолчанию — для тестов, чтобы не тащить прошлый прогон."""
    global language, fullscreen
    language = LANG_RU
    fullscreen = False
    config.WIDTH = config.WINDOW_WIDTH
    config.HEIGHT = config.WINDOW_HEIGHT


def load() -> None:
    global language, fullscreen
    if not SETTINGS_PATH.is_file():
        return
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    lang = data.get("language")
    if lang in LANGUAGES:
        language = lang
    fullscreen = bool(data.get("fullscreen", False))


def save() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"language": language, "fullscreen": fullscreen}, indent=2),
        encoding="utf-8",
    )


def set_language(lang: str) -> None:
    global language
    if lang not in LANGUAGES:
        return
    language = lang
    save()


def cycle_language() -> None:
    index = LANGUAGES.index(language) if language in LANGUAGES else 0
    set_language(LANGUAGES[(index + 1) % len(LANGUAGES)])


def _desktop_size() -> tuple[int, int]:
    try:
        sizes = pygame.display.get_desktop_sizes()
        if sizes:
            return int(sizes[0][0]), int(sizes[0][1])
    except pygame.error:
        pass
    return config.WINDOW_WIDTH, config.WINDOW_HEIGHT


def apply_display() -> pygame.Surface:
    """Ставит окно по текущим настройкам и обновляет config.WIDTH/HEIGHT."""
    if fullscreen:
        width, height = _desktop_size()
        flags = pygame.NOFRAME
    else:
        width, height = config.WINDOW_WIDTH, config.WINDOW_HEIGHT
        flags = 0
    config.WIDTH, config.HEIGHT = width, height
    return pygame.display.set_mode((width, height), flags)


def set_fullscreen(value: bool) -> pygame.Surface:
    global fullscreen
    fullscreen = value
    save()
    return apply_display()


def toggle_fullscreen() -> pygame.Surface:
    return set_fullscreen(not fullscreen)
