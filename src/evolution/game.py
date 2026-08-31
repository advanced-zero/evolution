"""Основной игровой цикл: держит текущий экран и передаёт ему управление."""

import pygame

from evolution import config, settings
from evolution.water import sync_window


class Game:
    def __init__(self) -> None:
        pygame.init()
        settings.load()
        self.screen = settings.apply_display()
        sync_window()
        pygame.display.set_caption(config.TITLE)
        self.clock = pygame.time.Clock()
        self.running = False

        from evolution.scenes import EditorScene

        self.scene = EditorScene()

    def run(self) -> None:
        self.running = True
        while self.running:
            dt = min(self.clock.tick(config.FPS) / 1000.0, 0.05)
            self.handle_events()
            if getattr(self.scene, "wants_quit", False):
                self.running = False
                break
            next_scene = self.scene.update(dt)
            if next_scene is not None:
                self.scene = next_scene
            self.scene.draw(self.screen)
            pygame.display.flip()
        pygame.quit()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            else:
                self.scene.handle_event(event)
                surface = pygame.display.get_surface()
                if surface is not None and surface is not self.screen:
                    self.screen = surface
                    sync_window()
