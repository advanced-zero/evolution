"""Меню по Esc: затемнение поверх текущего экрана."""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from evolution import config, render, settings
from evolution.i18n import t

PAGE_ROOT = "root"
PAGE_OPTIONS = "options"
PAGE_CONFIRM_QUIT = "confirm_quit"
PAGE_CONFIRM_EDITOR = "confirm_editor"


@dataclass
class _Item:
    action: str
    rect: pygame.Rect
    label: str


class Menu:
    """Одно меню для редактора, боя и гибели."""

    def __init__(self, *, from_editor: bool) -> None:
        self.from_editor = from_editor
        self.open = False
        self.page = PAGE_ROOT
        self.index = 0
        self.wants_quit = False
        self.wants_editor = False
        self.font = render.get_font(22)
        self.big_font = render.get_font(36, bold=True)
        self._items: list[_Item] = []

    def show(self) -> None:
        self.open = True
        self.page = PAGE_ROOT
        self.index = 0
        self.wants_quit = False
        self.wants_editor = False

    def hide(self) -> None:
        self.open = False
        self.page = PAGE_ROOT
        self.index = 0

    def _back(self) -> None:
        if self.page == PAGE_ROOT:
            self.hide()
        else:
            self.page = PAGE_ROOT
            self.index = 0

    def handle_event(self, event: pygame.event.Event) -> bool:
        """True — событие съедено меню (экран его не трогает)."""
        if not self.open:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.show()
                return True
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._back()
                return True
            if event.key in (pygame.K_UP, pygame.K_w):
                self._move(-1)
                return True
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self._move(1)
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate(self.index)
                return True
        elif event.type == pygame.MOUSEMOTION:
            for i, item in enumerate(self._items):
                if item.rect.collidepoint(event.pos):
                    self.index = i
            return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, item in enumerate(self._items):
                if item.rect.collidepoint(event.pos):
                    self.index = i
                    self._activate(i)
                    break
            return True
        elif event.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL):
            return True
        return True

    def _move(self, step: int) -> None:
        n = len(self._page_specs())
        if n == 0:
            return
        self.index = (self.index + step) % n

    def _activate(self, index: int) -> None:
        specs = self._page_specs()
        if not (0 <= index < len(specs)):
            return
        action = specs[index][0]
        if action == "editor":
            if self.from_editor:
                self.hide()
            else:
                self.page = PAGE_CONFIRM_EDITOR
                self.index = 0
        elif action == "options":
            self.page = PAGE_OPTIONS
            self.index = 0
        elif action == "quit":
            self.page = PAGE_CONFIRM_QUIT
            self.index = 0
        elif action == "back":
            self._back()
        elif action == "fullscreen":
            settings.toggle_fullscreen()
        elif action == "language":
            settings.cycle_language()
        elif action == "confirm_quit":
            self.wants_quit = True
        elif action == "confirm_editor":
            self.wants_editor = True
            self.hide()
        elif action == "cancel":
            self.page = PAGE_ROOT
            self.index = 0

    def draw(self, surface: pygame.Surface) -> None:
        if not self.open:
            self._items = []
            return
        dim = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, config.MENU_DIM_ALPHA))
        surface.blit(dim, (0, 0))

        specs = self._page_specs()
        panel_h = 90 + 50 * len(specs) + 36
        panel = pygame.Rect(0, 0, 520, panel_h)
        panel.center = (config.WIDTH // 2, config.HEIGHT // 2)
        pygame.draw.rect(surface, config.MENU_PANEL, panel, border_radius=12)
        pygame.draw.rect(surface, config.BORDER_COLOR, panel, width=1, border_radius=12)

        title_key = {
            PAGE_ROOT: "menu.title",
            PAGE_OPTIONS: "opt.title",
            PAGE_CONFIRM_QUIT: "menu.confirm_quit",
            PAGE_CONFIRM_EDITOR: "menu.confirm_editor",
        }[self.page]
        title_font = self.font if self.page.startswith("confirm") else self.big_font
        title = title_font.render(t(title_key), True, config.FG_COLOR)
        surface.blit(title, title.get_rect(center=(panel.centerx, panel.top + 36)))

        self._items = []
        y = panel.top + 80
        for i, (action, label) in enumerate(specs):
            rect = pygame.Rect(panel.left + 40, y, panel.width - 80, 40)
            hot = i == self.index
            pygame.draw.rect(
                surface,
                config.MENU_BUTTON_HOT if hot else config.MENU_BUTTON,
                rect,
                border_radius=8,
            )
            text = self.font.render(label, True, config.FG_COLOR)
            surface.blit(text, text.get_rect(center=rect.center))
            self._items.append(_Item(action, rect, label))
            y += 50
        if self._items:
            self.index %= len(self._items)

    def _page_specs(self) -> list[tuple[str, str]]:
        if self.page == PAGE_ROOT:
            return [
                ("editor", t("menu.editor")),
                ("options", t("menu.options")),
                ("quit", t("menu.quit")),
            ]
        if self.page == PAGE_OPTIONS:
            on = t("opt.fullscreen.on") if settings.fullscreen else t("opt.fullscreen.off")
            lang = t("opt.lang.ru") if settings.language == settings.LANG_RU else t("opt.lang.en")
            return [
                ("fullscreen", t("opt.fullscreen", value=on)),
                ("language", t("opt.language", value=lang)),
                ("back", t("menu.back")),
            ]
        yes, no = t("menu.yes"), t("menu.no")
        if self.page == PAGE_CONFIRM_QUIT:
            return [("confirm_quit", yes), ("cancel", no)]
        return [("confirm_editor", yes), ("cancel", no)]
