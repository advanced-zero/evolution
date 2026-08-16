"""Чит-коды для тестирования игры — не часть баланса, только для отладки.

Чтобы убрать читы совсем: удали этот файл, импорт/использование `Cheats` в
`scenes.py`, крючки `cheats=` в `World.update`/`World._collisions`
(world.py) и `Creature.heal_full` (creature.py, помечен как чит в докстринге).
"""

from __future__ import annotations

import pygame

from evolution.world import World


class Cheats:
    """Тумблеры и разовые действия по F1-F5 во время заплыва (PlayScene)."""

    def __init__(self) -> None:
        self.energy = False
        self.invuln = False

    def handle_event(self, event: pygame.event.Event, world: World) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_F1:
            self.energy = not self.energy
        elif event.key == pygame.K_F2:
            world.player.heal_full()
        elif event.key == pygame.K_F3:
            world.enemies.clear()
            world.brains.clear()  # мир сам досоздаст врагов на следующем шаге
        elif event.key == pygame.K_F4:
            world.spawn_enemy()
        elif event.key == pygame.K_F5:
            self.invuln = not self.invuln

    def hint_line(self) -> str:
        return "Читы: F1 энергия, F2 ремонт, F3 убить врагов, F4 враг, F5 неуязвимость."

    def status_line(self) -> str | None:
        active = []
        if self.energy:
            active.append("энергия")
        if self.invuln:
            active.append("неуязвимость")
        return "ЧИТЫ: " + " / ".join(active) if active else None
