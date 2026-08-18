"""Проверка правил игры без окна: гексы, отрыв клеток, лечение, движение, мир."""

from __future__ import annotations

import math

import random

from evolution import config, hexgrid, physics
from evolution.creature import (
    BONE,
    EYE,
    PHOTOSYNTH,
    PROCESSOR,
    ROOT,
    SKIN,
    THRUSTER,
    Blueprint,
    CellSpec,
    Creature,
    Muscle,
    default_blueprint,
)
from evolution.world import Food, World


def line_blueprint(length: int, kind: str = SKIN) -> Blueprint:
    bp = Blueprint()
    for i in range(1, length):
        bp.place(CellSpec((i, 0), kind))
    return bp


def tail_blueprint(length: int, kind: str = SKIN) -> Blueprint:
    """Хвост из клеток нужного вида с двигателем на самом кончике."""
    bp = line_blueprint(length, kind)
    bp.cells[(length - 1, 0)] = CellSpec((length - 1, 0), THRUSTER, direction=0, group=1)
    return bp


def eel_blueprint(length: int = 6, strength: int = 6) -> Blueprint:
    """Угорь: хребет и по мышце вдоль каждого бока — как настоящая рыба.

    Мышца гнёт тело, только если идёт вдоль бока: натянутая по середине она
    просто складывает тело гармошкой.
    """
    bp = Blueprint()
    for i in range(1, length):
        bp.place(CellSpec((-i, 0), SKIN))
    for i in range(0, length - 1):
        bp.place(CellSpec((-i, -1), SKIN))
        bp.place(CellSpec((-i - 1, 1), SKIN))
    bp.add_muscle(Muscle((0, -1), (-length + 2, -1), group=1, strength=strength))
    bp.add_muscle(Muscle((-1, 1), (-length + 1, 1), group=2, strength=strength))
    return bp


def squeeze_body(creature: Creature, amount: float) -> None:
    """Сминает тело к мозгу: все связи становятся короче на `amount` долю."""
    brain_x, brain_y = creature.rest_pos(ROOT)
    for coord in creature.alive_cells:
        if coord == ROOT:
            continue
        rest_x, rest_y = creature.rest_pos(coord)
        creature.offsets[coord][0] = -(rest_x - brain_x) * amount
        creature.offsets[coord][1] = -(rest_y - brain_y) * amount
    creature._recompute_squeeze()


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


def test_player_thruster_overheats_and_cools_down() -> None:
    """Игрок держит кнопку долго — двигатель уходит в колдаун, соседняя кнопка цела."""
    bp = Blueprint()
    bp.place(CellSpec((-1, 0), THRUSTER, direction=0, group=1))
    bp.place(CellSpec((1, 0), THRUSTER, direction=0, group=2))
    creature = Creature(blueprint=bp, x=500.0, y=500.0, is_player=True)
    dt = 1 / 60
    steps = int(config.THRUSTER_OVERHEAT_TIME / dt) + 5
    for _ in range(steps):
        creature.apply_thrust({1}, dt)
        creature.step(dt)
    assert creature.thruster_cooldown.get(1, 0.0) > 0.0
    assert creature.thruster_heat.get(2, 0.0) == 0.0  # кнопку 2 не трогали — не грелась

    vx_at_cooldown = creature.vx
    for _ in range(30):
        creature.apply_thrust({1}, dt)  # держим дальше — толчка быть не должно
        creature.step(dt)
    assert creature.vx <= vx_at_cooldown + 1.0

    while creature.thruster_cooldown.get(1, 0.0) > 0.0:
        creature.apply_thrust(set(), dt)
        creature.step(dt)
    vx_before_resume = creature.vx
    for _ in range(30):
        creature.apply_thrust({1}, dt)
        creature.step(dt)
    assert creature.vx > vx_before_resume + 1.0  # после колдауна снова толкает


def test_player_thruster_rapid_toggle_still_overheats() -> None:
    """Частое дёрганье кнопки короткими паузами не должно спасать от перегрева."""
    bp = Blueprint()
    bp.place(CellSpec((-1, 0), THRUSTER, direction=0, group=1))
    creature = Creature(blueprint=bp, x=500.0, y=500.0, is_player=True)
    dt = 1 / 60
    chunk = max(1, round(0.1 / dt))  # держим 0.1с, отпускаем 0.1с — короче THRUSTER_COOL_GRACE

    held = True
    overheated = False
    for _ in range(600):  # с запасом на много циклов туда-сюда
        for _ in range(chunk):
            creature.apply_thrust({1} if held else set(), dt)
            creature.step(dt)
            if creature.thruster_cooldown.get(1, 0.0) > 0.0:
                overheated = True
                break
        if overheated:
            break
        held = not held
    assert overheated  # короткие паузы не должны спасать от колдауна

    # а вот заметная пауза (дольше THRUSTER_COOL_GRACE) жар реально остужает
    creature2 = Creature(blueprint=bp, x=500.0, y=500.0, is_player=True)
    for _ in range(int(1.0 / dt)):  # держим секунду — жара накопилось, но не до перегрева
        creature2.apply_thrust({1}, dt)
        creature2.step(dt)
    heat_before = creature2.thruster_heat.get(1, 0.0)
    assert heat_before > 0.0
    for _ in range(int((config.THRUSTER_COOL_GRACE + 0.3) / dt)):  # пауза длиннее грани
        creature2.apply_thrust(set(), dt)
        creature2.step(dt)
    assert creature2.thruster_heat.get(1, 0.0) < heat_before


def _delivered_thrust(blueprint: Blueprint, steps: int = 120) -> float:
    """Сколько толчка двигателя реально дошло до тела (масса × набранный ход)."""
    creature = Creature(blueprint=blueprint, x=1000.0, y=1000.0)
    for _ in range(steps):
        creature.apply_thrust({1}, 1 / 60)
        creature.step(1 / 60)
    return creature.mass * math.hypot(creature.vx, creature.vy)


def _kink(creature: Creature) -> float:
    """Самый крутой излом в теле, в градусах: у жёсткого куска он около нуля."""
    worst = 0.0
    for coord in creature.alive_cells:
        worst = max(worst, math.degrees(creature._joint_bend(coord)))
    return worst


def _piece_distortion(creature: Creature) -> float:
    """На сколько пикселей костяной кусок отступил от своей формы в чертеже."""
    worst = 0.0
    for piece in creature.bone_pieces:
        for i, a in enumerate(piece):
            ax, ay = creature.local_pos(a)
            rax, ray = creature.rest_pos(a)
            for b in piece[i + 1 :]:
                bx, by = creature.local_pos(b)
                rbx, rby = creature.rest_pos(b)
                now = math.hypot(bx - ax, by - ay)
                rest = math.hypot(rbx - rax, rby - ray)
                worst = max(worst, abs(now - rest))
    return worst


def test_soft_tail_bends_but_bone_does_not() -> None:
    """На развороте кожаный хвост изгибается, костяной остаётся прямым.

    Костяной хвост при этом вполне может качнуться целиком — кость подвижна,
    просто не гнётся. Поэтому смотрим не на смещение, а на излом.
    """

    def swing(kind: str) -> tuple[float, float, float | None]:
        creature = Creature(blueprint=tail_blueprint(6, kind), x=2000.0, y=1500.0)
        for _ in range(60):
            creature.apply_thrust({1}, 1 / 60)
            creature.step(1 / 60)
        creature.spin += 6.0  # резкий разворот
        peak, distortion, settle = 0.0, 0.0, None
        for i in range(300):
            creature.step(1 / 60)
            kink = _kink(creature)
            peak = max(peak, kink)
            distortion = max(distortion, _piece_distortion(creature))
            if settle is None and i > 10 and kink < 1.0:
                settle = i / 60
        return peak, distortion, settle

    soft_peak, _, soft_settle = swing(SKIN)
    _, hard_distortion, _ = swing(BONE)
    assert soft_peak > 10.0, "мягкий хвост должен заметно изгибаться"
    # кость подвижна и может качнуться целиком — но форму куска обязана держать
    assert hard_distortion < 1.0, f"костяной кусок повело на {hard_distortion:.1f} px"
    # «тягуче, как желе»: качается заметное время, но всё-таки выпрямляется
    assert soft_settle is not None and 0.3 < soft_settle < 3.0


def lever_blueprint(left: str, right: str) -> Blueprint:
    """Полоска кожи, на концах — по клетке нужного вида, между ними мышца."""
    bp = Blueprint()
    for i in range(1, 6):
        bp.place(CellSpec((-i, 0), SKIN))
    bp.cells[(-1, 0)].kind = left
    bp.cells[(-5, 0)].kind = right
    bp.add_muscle(Muscle((-1, 0), (-5, 0), group=1, strength=8))
    return bp


def _muscle_gap(creature: Creature) -> float:
    ax, ay = creature.local_pos((-1, 0))
    bx, by = creature.local_pos((-5, 0))
    return math.hypot(bx - ax, by - ay)


def test_muscle_moves_a_bone() -> None:
    """Кость — рычаг: мышца между двумя костями сближает их почти как кожу.

    Раньше кость была прибита к своему месту в чертеже и не двигалась вовсе —
    мышца тянула, а кости просто висели.
    """

    def pulled(left: str, right: str) -> float:
        creature = Creature(blueprint=lever_blueprint(left, right), x=1000.0, y=1000.0)
        before = _muscle_gap(creature)
        for _ in range(60):
            creature.apply_muscles({1}, 1 / 60)
            creature.step(1 / 60)
        return 1.0 - _muscle_gap(creature) / before

    soft = pulled(SKIN, SKIN)
    bone = pulled(BONE, BONE)
    assert bone > 0.5, f"кость должна поддаваться мышце, а сдвинулась на {bone:.0%}"
    assert bone > soft * 0.7, "и не сильно упрямее кожи"


def test_bone_lever_returns_to_its_pose() -> None:
    """Отпустили мышцу — кость сама встала на своё место в чертеже."""
    creature = Creature(blueprint=lever_blueprint(BONE, BONE), x=1000.0, y=1000.0)
    before = _muscle_gap(creature)
    for _ in range(60):
        creature.apply_muscles({1}, 1 / 60)
        creature.step(1 / 60)
    assert _muscle_gap(creature) < before * 0.6, "мышца должна была стянуть кости"

    for _ in range(120):
        creature.apply_muscles(set(), 1 / 60)  # кнопку отпустили
        creature.step(1 / 60)
    assert _muscle_gap(creature) > before * 0.95, "рычаг обязан вернуться в позу"


def bone_fin_blueprint() -> Blueprint:
    """Хвост из кожи и костяной «плавник» из трёх клеток, стянутый мышцей."""
    bp = Blueprint()
    for i in range(1, 5):
        bp.place(CellSpec((-i, 0), SKIN))
    for coord in ((0, -1), (1, -2), (2, -3)):
        bp.place(CellSpec(coord, BONE))
    bp.add_muscle(Muscle((2, -3), (-4, 0), group=1, strength=8))
    return bp


def test_bone_piece_moves_whole_and_keeps_its_shape() -> None:
    """Кости вплотную — одна цельная кость: едет и поворачивается, но не гнётся."""
    creature = Creature(blueprint=bone_fin_blueprint(), x=1000.0, y=1000.0)
    assert len(creature.bone_pieces) == 1
    assert len(creature.bone_pieces[0]) == 3

    moved = 0.0
    for _ in range(60):
        creature.apply_muscles({1}, 1 / 60)
        creature.step(1 / 60)
        moved = max(moved, max(math.hypot(*creature.offsets[c]) for c in creature.bone_pieces[0]))

    assert moved > 10.0, "мышца должна ворочать плавник целиком"
    assert _piece_distortion(creature) < 1.0, "а форма внутри куска обязана держаться"


def test_bone_piece_pivots_around_the_brain() -> None:
    """Кость, приросшая к мозгу, поворачивается вокруг него, а мозг стоит."""
    creature = Creature(blueprint=bone_fin_blueprint(), x=1000.0, y=1000.0)
    for _ in range(60):
        creature.apply_muscles({1}, 1 / 60)
        creature.step(1 / 60)
    assert math.hypot(*creature.offsets[ROOT]) < 1e-6, "мозг не смещается"
    # клетка кости, приросшая к мозгу, держится от него на прежнем расстоянии
    bx, by = creature.local_pos(ROOT)
    nx, ny = creature.local_pos((0, -1))
    assert abs(math.hypot(nx - bx, ny - by) - config.HEX_STEP) < config.HEX_STEP * 0.15


def test_bone_carries_thrust_better_than_skin() -> None:
    """Через костяной скелет толчок доходит до тела, через мягкую ножку — вяло.

    Скорость при этом у костяного тела ниже: кость тяжёлая. Выигрыш не в
    скорости, а в том, что двигатель работает не впустую.
    """
    soft = Creature(blueprint=tail_blueprint(5, SKIN))
    hard = Creature(blueprint=tail_blueprint(5, BONE))
    assert hard.transmit[(4, 0)] > soft.transmit[(4, 0)] * 1.5
    assert _delivered_thrust(tail_blueprint(5, BONE)) > _delivered_thrust(tail_blueprint(5, SKIN))


def test_brain_does_not_move_inside_the_body() -> None:
    creature = Creature(blueprint=tail_blueprint(5, SKIN), x=1000.0, y=1000.0)
    for _ in range(30):
        creature.apply_thrust({1}, 1 / 60)
        creature.step(1 / 60)
    assert math.hypot(*creature.offsets[ROOT]) < 1e-6


def _pull_apart(creature: Creature, coord: tuple[int, int], times: float = 2.0) -> None:
    """Растаскивает клетку и её соседа дальше, чем связь способна выдержать."""
    creature.offsets[coord][0] = config.HEX_STEP * config.SOFT_TEAR_STRETCH * times


def test_stretched_link_tears_off() -> None:
    """Рвёт не изгиб, а разрыв: растащили соседей — клетка отвалилась."""
    world = World(default_blueprint(), seed=11)
    creature = Creature(blueprint=line_blueprint(3), x=1000.0, y=1000.0)
    world.enemies.append(creature)
    _pull_apart(creature, (2, 0))

    creature.step(1 / 60)
    assert (2, 0) in creature.torn

    # а кость такое держит: её можно потерять только от тарана
    bone = Creature(blueprint=line_blueprint(3, BONE), x=1000.0, y=1000.0)
    _pull_apart(bone, (2, 0))
    bone.step(1 / 60)
    assert not bone.torn

    before = len(world.foods)
    world.lose_cell(creature, (2, 0))
    assert (2, 0) not in creature.alive_cells
    assert len(world.foods) == before + 1


def _worst_link_stretch(creature: Creature) -> float:
    """Во сколько раз самая растянутая связь длиннее покоя."""
    worst = 0.0
    for a in creature.alive_cells:
        ax, ay = creature.local_pos(a)
        for b in hexgrid.neighbors(a):
            if b in creature.alive_cells:
                bx, by = creature.local_pos(b)
                worst = max(worst, math.hypot(bx - ax, by - ay) / config.HEX_STEP)
    return worst


def _worst_overlap(creature: Creature) -> float:
    """На сколько пикселей ближе всего сошлись клетки, которые не соседи."""
    worst = 0.0
    cells = sorted(creature.alive_cells)
    for i, a in enumerate(cells):
        ax, ay = creature.local_pos(a)
        for b in cells[i + 1 :]:
            if hexgrid.distance(a, b) <= 1:
                continue
            bx, by = creature.local_pos(b)
            worst = max(worst, config.HEX_STEP - math.hypot(bx - ax, by - ay))
    return worst


def test_body_holds_together() -> None:
    """При обычной работе мышц щелей между клетками не появляется.

    Мышца на полную силу — отдельный случай: там тело сперва растягивается,
    а потом рвётся, и это проверяет `test_overpulled_muscle_tears_the_body`.
    """
    creature = Creature(blueprint=eel_blueprint(strength=5), x=1000.0, y=1000.0)
    worst = 0.0
    for _ in range(60):
        creature.apply_muscles({1}, 1 / 60)
        creature.step(1 / 60)
        worst = max(worst, _worst_link_stretch(creature))
    assert worst < 1.1, f"связи растянулись до {worst:.2f}× — это уже щели"


def test_cells_do_not_pass_through_each_other() -> None:
    """Мышца складывает тело, но клетки не проходят друг сквозь друга."""
    creature = Creature(blueprint=eel_blueprint(strength=8), x=1000.0, y=1000.0)
    worst = 0.0
    for _ in range(60):
        creature.apply_muscles({1}, 1 / 60)
        creature.step(1 / 60)
        worst = max(worst, _worst_overlap(creature))
    assert worst < config.HEX_STEP * 0.35, f"клетки налезли на {worst:.1f} px"


def test_cell_cannot_orbit_its_neighbour() -> None:
    """Клетку не увести вокруг соседа сквозь тело: либо упрётся, либо оторвётся."""
    creature = Creature(blueprint=line_blueprint(4, SKIN), x=1000.0, y=1000.0)
    # тащим кончик хвоста назад к мозгу, будто обводим его вокруг соседа
    rest_x, rest_y = creature.rest_pos((3, 0))
    near_x, near_y = creature.rest_pos((1, 0))
    creature.offsets[(3, 0)][0] = near_x - rest_x
    creature.offsets[(3, 0)][1] = near_y - rest_y + 4.0
    creature.step(1 / 60)

    assert creature.torn or _worst_overlap(creature) < config.HEX_STEP * 0.35


def test_joint_bend_measures_the_kink() -> None:
    """Излом в суставе: прямое тело — ноль, сложенное вдвое — почти развёрнутый угол."""
    creature = Creature(blueprint=line_blueprint(4, SKIN), x=1000.0, y=1000.0)
    assert creature._joint_bend((1, 0)) < 1e-6  # чертёж не изломан

    # уводим кончик назад, к мозгу: сустав в (1, 0) складывается вдвое
    rest_x, rest_y = creature.rest_pos((2, 0))
    back_x, back_y = creature.rest_pos(ROOT)
    creature.offsets[(2, 0)][0] = back_x - rest_x
    creature.offsets[(2, 0)][1] = back_y - rest_y + config.HEX_STEP * 0.3
    assert creature._joint_bend((1, 0)) > config.SOFT_BEND_LIMIT


def test_overpulled_muscle_tears_the_body() -> None:
    """Слабая мышца тело только гнёт, а чрезмерная — рвёт."""

    def pull(strength: int) -> Creature:
        creature = Creature(blueprint=eel_blueprint(strength=strength), x=1000.0, y=1000.0)
        for _ in range(90):
            creature.apply_muscles({1}, 1 / 60)
            creature.step(1 / 60)
            if creature.torn:
                break
        return creature

    assert not pull(4).torn, "обычная мышца тело не рвёт"
    assert pull(10).torn, "мышца на всю силу должна порвать тонкое тело"


def test_body_squeezes_but_bone_does_not() -> None:
    """Мягкое тело сминается, костяное держит размер."""
    soft = Creature(blueprint=line_blueprint(4, SKIN), x=1000.0, y=1000.0)
    hard = Creature(blueprint=line_blueprint(4, BONE), x=1000.0, y=1000.0)
    squeeze_body(soft, 0.25)
    squeeze_body(hard, 0.25)
    assert soft.squeeze_at((3, 0)) > 0.15
    assert hard.squeeze_at((3, 0)) == 0.0


def test_squeeze_absorbs_the_blow() -> None:
    """Смятая клетка держит удар, от которого целая отлетает."""
    speed = config.DAMAGE_SPEED * 1.3

    def loses_cell(squeezed: bool) -> bool:
        rammer, target = ram_pair(SKIN, SKIN)
        if squeezed:
            squeeze_body(target, 0.3)
        rammer.vx = speed
        return any(c is target for c, _ in physics.collide_pair(rammer, target))

    assert loses_cell(False), "целую клетку такой удар выбивает"
    assert not loses_cell(True), "а смятая его гасит"


def test_crushed_cell_bursts() -> None:
    """Смяло до предела — клетка лопается и уходит обломком."""
    world = World(default_blueprint(), seed=13)
    creature = Creature(blueprint=line_blueprint(4), x=1000.0, y=1000.0)
    world.enemies.append(creature)
    squeeze_body(creature, config.SOFT_BURST + 0.1)

    assert creature.torn, "смятая в лепёшку клетка должна лопнуть"
    victim = creature.torn[0]
    before = len(world.foods)
    world.lose_cell(creature, victim)
    assert victim not in creature.alive_cells
    assert len(world.foods) > before


def test_muscle_costs_by_length_and_bends_the_body() -> None:
    """Мышца стоит по очку за клетку длины и стягивает свои концы."""
    bp = eel_blueprint()
    assert bp.muscles[0].cost() == bp.muscles[0].length() == 4
    cells_only = sum(1 for _ in bp.cells)
    assert bp.cost() == cells_only + 4 + 4  # клетки плюс обе мышцы

    creature = Creature(blueprint=bp, x=1000.0, y=1000.0)
    a, b = bp.muscles[0].a, bp.muscles[0].b
    before = math.dist(creature.local_pos(a), creature.local_pos(b))
    for _ in range(45):
        creature.apply_muscles({1}, 1 / 60)
        creature.step(1 / 60)
    after = math.dist(creature.local_pos(a), creature.local_pos(b))
    assert after < before * 0.8, "мышца должна заметно подтянуть концы"
    # и тело при этом уходит вбок, а не просто складывается вдоль
    assert abs(creature.offsets[(-5, 0)][1]) > 5.0


def test_stronger_muscle_bends_more() -> None:
    """Сила мышцы — это сила: слабая едва гнёт, сильная складывает тело."""

    def bend(strength: int) -> float:
        creature = Creature(blueprint=eel_blueprint(strength=strength), x=1000.0, y=1000.0)
        peak = 0.0
        for _ in range(45):
            creature.apply_muscles({1}, 1 / 60)
            creature.step(1 / 60)
            peak = max(peak, max(math.hypot(*o) for o in creature.offsets.values()))
        return peak

    assert bend(8) > bend(2) * 2.0


def test_muscle_eats_only_when_working() -> None:
    """Мышца просит энергию по силе и только за отработанное время."""
    creature = Creature(blueprint=eel_blueprint(strength=4), x=1000.0, y=1000.0)
    creature.since_hunger = 10.0
    assert creature.muscle_demand() == 0.0  # никто не тянул

    creature.muscle_work[0] = 10.0  # тянула весь интервал
    assert creature.muscle_demand() == config.MUSCLE_WORK_UPKEEP * 4
    creature.muscle_work[0] = 5.0  # полинтервала — половина цены
    assert creature.muscle_demand() == config.MUSCLE_WORK_UPKEEP * 4 * 0.5


def test_muscles_survive_saving() -> None:
    bp = eel_blueprint(strength=7)
    loaded = Blueprint.from_json(bp.to_json())
    assert len(loaded.muscles) == 2
    assert loaded.muscles[0].strength == 7
    assert loaded.cost() == bp.cost()


def test_waving_tail_pushes_a_little() -> None:
    """Виляние хвостом даёт ход — пусть небольшой, но в плюс."""
    creature = Creature(blueprint=eel_blueprint(strength=8), x=2000.0, y=1500.0)
    start = (creature.x, creature.y)
    t = 0.0
    while t < 6.0:
        half = (t % config.MUSCLE_STROKE_PERIOD) < config.MUSCLE_STROKE_PERIOD / 2
        creature.apply_muscles({1} if half else {2}, 1 / 60)
        creature.step(1 / 60)
        t += 1 / 60
    assert math.hypot(creature.x - start[0], creature.y - start[1]) > 10.0


def test_bent_body_does_not_tear_itself() -> None:
    """Свернуться дугой можно: пока соседи держатся, тело целое."""
    creature = Creature(blueprint=tail_blueprint(6, SKIN), x=1000.0, y=1000.0)
    # уводим весь хвост вбок, не растаскивая соседей друг от друга
    for i, coord in enumerate(sorted(creature.alive_cells, key=lambda c: hexgrid.distance(ROOT, c))):
        creature.offsets[coord][1] = i * 4.0
    creature.step(1 / 60)
    assert not creature.torn


def ram_pair(left_kind: str, right_kind: str) -> tuple[Creature, Creature]:
    """Двое лоб в лоб: у левого выступает клетка вправо, у правого — влево.

    Клетки сдвинуты так, что вот-вот столкнутся именно эти два выступа.
    """
    left_bp = Blueprint()
    left_bp.place(CellSpec((1, 0), left_kind))
    right_bp = Blueprint()
    right_bp.place(CellSpec((-1, 0), right_kind))

    right = Creature(blueprint=right_bp, x=1000.0, y=1000.0)
    left = Creature(blueprint=left_bp, x=1000.0, y=1000.0)
    tip_x, _ = right.cell_world_pos((-1, 0))
    nose_x, _ = left.cell_world_pos((1, 0))
    left.x += tip_x - nose_x - config.CELL_RADIUS * 1.7
    return left, right


def test_bone_is_harder_to_knock_out() -> None:
    """Удар, который вышибает кожу, о кость только звенит — да ещё и обламывает таран."""

    def hit(kind: str) -> list:
        rammer, target = ram_pair(SKIN, kind)
        rammer.vx = config.DAMAGE_SPEED * 1.4  # кожу берёт, кость — нет
        return [(creature is target, coord) for creature, coord in physics.collide_pair(rammer, target)]

    assert hit(SKIN) == [(True, (-1, 0))], "кожа от такого удара отлетает"
    bone_hits = hit(BONE)
    assert not any(is_target for is_target, _ in bone_hits), "кость удар держит"
    assert bone_hits, "а вот таранившему достаётся о кость"


def test_bone_rams_through_a_slower_hit() -> None:
    """Костяное остриё выбивает чужую клетку, даже когда само стоит на месте."""
    bone, target = ram_pair(BONE, SKIN)
    target.vx = -config.DAMAGE_SPEED * 1.4  # разогнался он, а не мы

    hits = physics.collide_pair(bone, target)
    assert hits, "такой удар должен что-то выбить"
    assert all(creature is target for creature, _ in hits), "кость пробивает, сама целая"


def test_budget_is_counted_in_points() -> None:
    bp = Blueprint()
    bp.place(CellSpec((1, 0), SKIN))
    bp.place(CellSpec((2, 0), BONE))
    assert bp.cost() == 1 + 1 + 3  # мозг, кожа и кость
    assert config.CELL_BUDGET == 50


def test_old_save_without_bones_loads() -> None:
    """Сохранение от версии без костей должно открываться как раньше."""
    old = '[{"q": 0, "r": 0, "kind": "skin", "dir": 0, "group": 1},'
    old += ' {"q": 1, "r": 0, "kind": "flesh", "dir": 2, "group": 3}]'
    bp = Blueprint.from_json(old)
    assert bp.cells[(1, 0)].kind == SKIN  # незнакомый вид считаем кожей
    assert bp.cells[(1, 0)].group == 3


def test_soft_body_never_pushes_itself() -> None:
    """Изгиб не должен разгонять существо: без двигателей вода обязана победить.

    Проверяем и мягкое тело, и хлыст от резкого вращения.
    """
    creature = Creature(blueprint=tail_blueprint(6, SKIN), x=2000.0, y=1500.0, vx=500.0)
    creature.spin = 6.0
    for _ in range(600):
        creature.step(1 / 60)
    assert math.hypot(creature.vx, creature.vy) < 20.0
    assert abs(creature.spin) < 0.5


def test_water_stops_the_creature() -> None:
    creature = Creature(blueprint=default_blueprint(), x=500.0, y=500.0, vx=400.0)
    for _ in range(240):
        creature.step(1 / 60)
    assert math.hypot(creature.vx, creature.vy) < 20.0


def test_dropped_cells_keep_their_look() -> None:
    bp = Blueprint()
    bp.place(CellSpec((1, 0), THRUSTER, direction=0, group=1))
    world = World(default_blueprint(), seed=3)

    enemy = Creature(blueprint=bp, x=400.0, y=400.0)
    world.drop_food(enemy, [ROOT, (1, 0)])
    by_color = {food.color for food in world.foods}
    assert by_color == {config.CORE_COLOR, config.ENEMY_THRUSTER_COLOR}
    thruster_food = next(f for f in world.foods if f.kind == THRUSTER)
    assert thruster_food.direction == 0

    world.foods.clear()
    player = Creature(blueprint=line_blueprint(2), x=400.0, y=400.0, is_player=True)
    world.drop_food(player, [(1, 0)])
    assert world.foods[0].color == config.SKIN_COLOR


def test_dropped_cell_keeps_spinning() -> None:
    piece = Food(x=100.0, y=100.0, vx=0.0, vy=0.0, spin=4.0)
    piece.step(1 / 60)
    assert piece.angle > 0.0


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


def test_body_starts_with_a_full_tank() -> None:
    """Бак считается от аппетита тела, и в заплыв выходим сытыми."""
    creature = Creature(blueprint=line_blueprint(3))
    assert creature.appetite == config.BRAIN_UPKEEP + 1 + 1  # мозг и две кожи
    assert creature.max_energy == creature.appetite * config.ENERGY_RESERVE
    assert creature.energy == creature.max_energy
    assert config.HUNGER_PERIOD_MIN <= creature.hunger_timer <= config.HUNGER_PERIOD_MAX


def test_hunger_takes_the_whole_appetite() -> None:
    """Удар голода списывает ровно столько, сколько тело просит."""
    creature = Creature(blueprint=line_blueprint(3))
    before = creature.energy
    assert creature.starve() == []  # энергии хватило, никого не потеряли
    assert creature.energy == before - creature.appetite


def test_bone_costs_nothing_to_keep() -> None:
    """Кость не ест: скелет ничего не стоит в содержании, только в постройке."""
    bony = Creature(blueprint=line_blueprint(3, BONE))
    soft = Creature(blueprint=line_blueprint(3, SKIN))
    assert bony.appetite == config.BRAIN_UPKEEP
    assert bony.appetite < soft.appetite


def test_working_thruster_costs_more() -> None:
    """Двигатель, жёгший топливо полинтервала, просит середину между 1 и 3."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), THRUSTER, direction=0, group=1))
    creature = Creature(blueprint=bp)
    assert creature.cell_demand((1, 0)) == 1.0  # стоял без дела

    creature.since_hunger = 10.0
    creature.work_time[(1, 0)] = 5.0
    assert creature.cell_demand((1, 0)) == 2.0

    creature.work_time[(1, 0)] = 10.0
    assert creature.cell_demand((1, 0)) == config.THRUSTER_WORK_UPKEEP


def test_photosynth_upkeep_is_fixed_within_an_interval() -> None:
    """Аппетит фотоклетки — случайный бросок, но один и тот же весь удар голода."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), PHOTOSYNTH))
    creature = Creature(blueprint=bp, rng=random.Random(0))
    demand = creature.cell_demand((1, 0))
    assert demand in (0.0, 1.0)
    # повторные обращения в пределах того же удара голода дают тот же ответ
    for _ in range(5):
        assert creature.cell_demand((1, 0)) == demand


def test_photosynth_feeds_the_body() -> None:
    """Фотоклетка сама приносит энергию на каждом ударе голода."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), PHOTOSYNTH))
    creature = Creature(blueprint=bp, rng=random.Random(0))
    creature.energy = creature.max_energy * 0.5  # с запасом, чтобы никого не потерять
    before = creature.energy
    own_demand = creature.cell_demand((1, 0))
    assert own_demand in (0.0, 1.0)
    creature.starve()
    gained = min(creature.max_energy, before + config.PHOTOSYNTH_ENERGY_GAIN) - before
    expected = before + gained - (config.BRAIN_UPKEEP + own_demand)
    assert creature.energy == expected
    assert creature.alive_cells == {ROOT, (1, 0)}  # никого не потеряли


def test_starving_body_sheds_the_farthest_cell() -> None:
    """Не хватило энергии — объедаемся с краёв, ближние к мозгу держатся."""
    creature = Creature(blueprint=line_blueprint(4))
    creature.energy = 4.0  # аппетит тела — 6
    lost = creature.starve()
    assert lost == [(3, 0), (2, 0)]
    assert creature.alive_cells == {ROOT, (1, 0)}
    assert not creature.is_dead
    assert creature.energy == 0.0


def test_hungry_brain_dies() -> None:
    """Мозг ест последним, и если даже ему не хватило — это смерть."""
    creature = Creature(blueprint=line_blueprint(2))
    creature.energy = 0.0
    creature.starve()
    assert creature.is_dead


def test_healing_costs_energy() -> None:
    """Дырка зарастает за столько же энергии, во сколько клетка обошлась в постройке."""
    creature = Creature(blueprint=line_blueprint(3, BONE))
    creature.remove_cell((2, 0))
    creature.energy = 2.0
    assert creature.heal(1) == 0  # кость стоит 3, на неё не хватает
    creature.energy = 3.0
    assert creature.heal(1) == 1
    assert creature.energy == 0.0
    assert creature.alive_cells == set(creature.blueprint.cells)


def test_repair_grows_cells_while_the_button_is_held() -> None:
    """Держим кнопку — клетки отрастают по REPAIR_RATE в секунду, пока есть энергия."""
    creature = Creature(blueprint=line_blueprint(4))
    creature.remove_cell((2, 0))
    creature.energy = 1.0
    assert creature.repair(1.0) == 1  # успели бы две, но энергии — на одну
    assert creature.energy == 0.0
    assert creature.lost_count == 1


def test_food_is_as_rich_as_the_cell_was() -> None:
    """Что дороже строить, то и сытнее: мозг — самая жирная добыча."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), BONE))
    bp.place(CellSpec((2, 0), SKIN))
    world = World(default_blueprint(), seed=11)
    world.foods.clear()

    enemy = Creature(blueprint=bp, x=400.0, y=400.0)
    world.drop_food(enemy, [ROOT, (1, 0), (2, 0)])
    # мозг сложен из кожи, но обломок с него — самый жирный
    assert sorted(food.energy for food in world.foods) == [
        config.FOOD_ENERGY[SKIN],
        config.FOOD_ENERGY[BONE],
        config.BRAIN_FOOD_ENERGY,
    ]


def lone_processor(x: float, y: float) -> Creature:
    """Существо из одной клетки-переработчика — удобно мерить расстояния точно."""
    bp = Blueprint()
    bp.cells[ROOT].kind = PROCESSOR
    creature = Creature(blueprint=bp, x=x, y=y)
    creature.energy = 0.0
    return creature


def test_touching_food_no_longer_feeds() -> None:
    """Обломок больше не подобрать касанием — его надо переварить."""
    world = World(default_blueprint(), seed=5)
    world.foods.clear()
    player = world.player
    player.energy = 0.0
    world.foods.append(Food(x=player.x, y=player.y, vx=0.0, vy=0.0, energy=5.0))

    world._food(1 / 60)
    assert player.energy == 0.0, "проплыть сквозь обломок теперь ничего не даёт"
    assert len(world.foods) == 1, "и сам обломок никуда не делся"


def test_processor_melts_food_faster() -> None:
    """Рядом с переработчиком обломок тает в PROCESS_SPEEDUP раз быстрее."""
    world = World(default_blueprint(), seed=5)
    world.enemies.clear()
    world.foods.clear()
    px, py = world.player.cell_world_pos((1, -1))  # клетка-переработчик

    near = Food(x=px, y=py, vx=0.0, vy=0.0)
    far = Food(x=px + 900.0, y=py, vx=0.0, vy=0.0)
    world.foods.extend([near, far])
    world._food(1.0)

    assert config.FOOD_LIFETIME - near.life == config.PROCESS_SPEEDUP
    assert config.FOOD_LIFETIME - far.life == 1.0, "вдали от переработчиков тает как обычно"


def test_two_processors_melt_twice_as_fast() -> None:
    """Переработчики складываются: вдвоём топят обломок вдвое быстрее."""
    world = World(default_blueprint(), seed=5)
    world.enemies.clear()
    world.foods.clear()

    bp = Blueprint()
    bp.place(CellSpec((1, 0), PROCESSOR))
    bp.place(CellSpec((1, -1), PROCESSOR))
    eater = Creature(blueprint=bp, x=1000.0, y=1000.0)
    world.enemies.append(eater)

    ax, ay = eater.cell_world_pos((1, 0))
    bx, by = eater.cell_world_pos((1, -1))
    food = Food(x=(ax + bx) / 2.0, y=(ay + by) / 2.0, vx=0.0, vy=0.0)
    world.foods.append(food)
    world._food(1.0)

    assert config.FOOD_LIFETIME - food.life == 2.0 * config.PROCESS_SPEEDUP


def test_energy_goes_to_the_nearest_processor() -> None:
    """Растворился обломок — всё забирает ближайший, соседу не достаётся ничего."""
    world = World(default_blueprint(), seed=5)
    world.player.x, world.player.y = 3500.0, 2500.0  # игрок далеко и не мешает
    world.enemies.clear()
    world.foods.clear()

    near = lone_processor(1000.0 + 40.0, 1000.0)
    far = lone_processor(1000.0 + 90.0, 1000.0)
    world.enemies.extend([near, far])
    world.foods.append(Food(x=1000.0, y=1000.0, vx=0.0, vy=0.0, life=0.005, energy=5.0))

    world._food(1 / 60)
    assert world.foods == []
    assert near.energy == 5.0
    assert far.energy == 0.0


def test_food_out_of_reach_is_wasted() -> None:
    """Дальше четырёх гексов обломок растворяется впустую."""
    world = World(default_blueprint(), seed=5)
    world.player.x, world.player.y = 3500.0, 2500.0
    world.enemies.clear()
    world.foods.clear()

    watcher = lone_processor(1000.0 + config.COLLECT_RADIUS + 10.0, 1000.0)
    world.enemies.append(watcher)
    world.foods.append(Food(x=1000.0, y=1000.0, vx=0.0, vy=0.0, life=0.005, energy=5.0))

    world._food(1 / 60)
    assert world.foods == []
    assert watcher.energy == 0.0


def test_processor_eats_only_while_working() -> None:
    """Простаивающий переработчик бесплатен, платим только за переработку."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), PROCESSOR))
    creature = Creature(blueprint=bp)
    assert creature.cell_demand((1, 0)) == 0.0

    creature.since_hunger = 10.0
    creature.work_time[(1, 0)] = 10.0
    assert creature.cell_demand((1, 0)) == config.PROCESSOR_WORK_UPKEEP


def test_full_creature_wastes_what_it_processed() -> None:
    """Сытому переработка ничего не даёт: сверх бака энергия не копится."""
    world = World(default_blueprint(), seed=5)
    world.player.x, world.player.y = 3500.0, 2500.0
    world.enemies.clear()
    world.foods.clear()

    eater = lone_processor(1000.0, 1000.0)
    eater.energy = eater.max_energy
    world.enemies.append(eater)
    world.foods.append(Food(x=1000.0, y=1000.0, vx=0.0, vy=0.0, life=0.005, energy=5.0))

    world._food(1 / 60)
    assert eater.energy == eater.max_energy


def test_eye_cell_lost_in_combat_stops_counting() -> None:
    """Живая зрительная клетка учитывается, выбитая — сразу пропадает из списка."""
    bp = Blueprint()
    bp.place(CellSpec((1, 0), EYE))
    bp.place(CellSpec((1, -1), EYE))
    creature = Creature(blueprint=bp)

    assert set(creature.eyes()) == {(1, 0), (1, -1)}

    creature.remove_cell((1, 0))
    assert creature.eyes() == [(1, -1)]


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"ok  {name}")
    print("Все проверки прошли.")
