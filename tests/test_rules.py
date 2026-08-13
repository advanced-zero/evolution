"""Проверка правил игры без окна: гексы, отрыв клеток, лечение, движение, мир."""

from __future__ import annotations

import math

from evolution import config, hexgrid
from evolution.creature import (
    ROOT,
    SKIN,
    THRUSTER,
    Blueprint,
    CellSpec,
    Creature,
    default_blueprint,
)
from evolution.world import World


def line_blueprint(length: int) -> Blueprint:
    bp = Blueprint()
    for i in range(1, length):
        bp.place(CellSpec((i, 0), SKIN))
    return bp


def test_hex_roundtrip() -> None:
    for coord in hexgrid.spiral(4):
        x, y = hexgrid.hex_to_pixel(coord, 20.0)
        assert hexgrid.pixel_to_hex(x, y, 20.0) == coord


def test_neighbors_are_adjacent() -> None:
    for n in hexgrid.neighbors((2, -1)):
        assert hexgrid.distance((2, -1), n) == 1


def test_losing_a_link_drops_everything_behind_it() -> None:
    creature = Creature(blueprint=line_blueprint(4))
    lost = creature.remove_cell((1, 0))
    assert set(lost) == {(1, 0), (2, 0), (3, 0)}
    assert creature.alive_cells == {ROOT}
    assert not creature.is_dead


def test_losing_the_core_kills() -> None:
    creature = Creature(blueprint=line_blueprint(3))
    lost = creature.remove_cell(ROOT)
    assert set(lost) == {ROOT, (1, 0), (2, 0)}
    assert creature.is_dead


def test_healing_never_grows_beyond_blueprint() -> None:
    creature = Creature(blueprint=line_blueprint(4))
    creature.remove_cell((2, 0))
    assert creature.lost_count == 2
    assert creature.heal(5) == 2
    assert creature.alive_cells == set(creature.blueprint.cells)
    assert creature.heal(3) == 0


def test_thruster_pushes_where_it_points() -> None:
    bp = Blueprint()
    bp.place(CellSpec((-1, 0), THRUSTER, direction=0, group=1))
    creature = Creature(blueprint=bp, x=500.0, y=500.0)
    for _ in range(10):
        creature.apply_thrust({1}, 1 / 60)
        creature.step(1 / 60)
    assert creature.vx > 50.0
    assert abs(creature.vy) < 1.0


def test_water_stops_the_creature() -> None:
    creature = Creature(blueprint=default_blueprint(), x=500.0, y=500.0, vx=400.0)
    for _ in range(240):
        creature.step(1 / 60)
    assert math.hypot(creature.vx, creature.vy) < 20.0


def test_world_runs_and_fight_happens() -> None:
    world = World(default_blueprint(), seed=7)
    assert len(world.enemies) == config.ENEMY_COUNT
    for step in range(1800):
        groups = {1} if step % 120 < 90 else {2}
        world.update(1 / 60, groups)
        assert len(world.enemies) == config.ENEMY_COUNT
        for creature in world.creatures():
            assert 0.0 <= creature.x <= config.WORLD_WIDTH
            assert 0.0 <= creature.y <= config.WORLD_HEIGHT


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"ok  {name}")
    print("Все проверки прошли.")
