"""Основной игровой цикл: держит текущий экран и передаёт ему управление."""

import pygame

from evolution import config


class Game:
    def __init__(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode((config.WIDTH, config.HEIGHT))
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
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
            else:
                self.scene.handle_event(event)
