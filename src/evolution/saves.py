"""Список сохранённых существ игрока: несколько файлов и текущее выбранное."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from evolution.creature import SAVE_PATH, Species, default_blueprint
from evolution.i18n import t

DATA_DIR = Path.home() / ".local" / "share" / "evolution"


@dataclass
class SaveInfo:
    id: str
    name: str


def saves_dir() -> Path:
    return DATA_DIR / "saves"


def index_path() -> Path:
    return DATA_DIR / "saves.json"


def _read_index() -> dict:
    path = index_path()
    if not path.is_file():
        return {"current": None, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"current": None, "entries": []}
    if not isinstance(data, dict):
        return {"current": None, "entries": []}
    entries = []
    for item in data.get("entries") or []:
        if not isinstance(item, dict):
            continue
        save_id = item.get("id")
        name = item.get("name", "")
        if isinstance(save_id, str) and save_id:
            entries.append({"id": save_id, "name": name if isinstance(name, str) else ""})
    current = data.get("current")
    if not isinstance(current, str):
        current = None
    return {"current": current, "entries": entries}


def _write_index(entries: list[SaveInfo], current: str | None) -> None:
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "current": current,
        "entries": [{"id": e.id, "name": e.name} for e in entries],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _entries() -> list[SaveInfo]:
    return [SaveInfo(item["id"], item["name"]) for item in _read_index()["entries"]]


def _next_id(entries: list[SaveInfo]) -> str:
    nums = [int(e.id) for e in entries if e.id.isdigit()]
    return str(max(nums, default=0) + 1)


def _default_name(entries: list[SaveInfo]) -> str:
    n = 1
    while True:
        name = t("saves.default_name", n=n)
        if all(e.name != name for e in entries):
            return name
        n += 1


def _file_for(save_id: str) -> Path:
    return saves_dir() / f"{save_id}.json"


def migrate_legacy() -> None:
    """Один раз переносит старый creature.json в список сохранений."""
    if index_path().is_file():
        return
    if not SAVE_PATH.is_file():
        return
    species = Species.load(SAVE_PATH)
    if species is None:
        return
    entries: list[SaveInfo] = []
    save_id = _next_id(entries)
    if not species.name:
        species.name = _default_name(entries)
    _file_for(save_id).parent.mkdir(parents=True, exist_ok=True)
    species.save(_file_for(save_id))
    info = SaveInfo(save_id, species.name)
    _write_index([info], save_id)


def list_saves() -> list[SaveInfo]:
    migrate_legacy()
    return _entries()


def current_id() -> str | None:
    migrate_legacy()
    current = _read_index()["current"]
    ids = {e.id for e in _entries()}
    if current in ids:
        return current
    return None


def set_current(save_id: str) -> None:
    entries = list_saves()
    if not any(e.id == save_id for e in entries):
        return
    _write_index(entries, save_id)


def load(save_id: str) -> Species | None:
    return Species.load(_file_for(save_id))


def load_current() -> Species | None:
    save_id = current_id()
    if save_id is None:
        return None
    return load(save_id)


def save_species(save_id: str, species: Species) -> None:
    species.save(_file_for(save_id))
    entries = list_saves()
    found = False
    updated: list[SaveInfo] = []
    for entry in entries:
        if entry.id == save_id:
            updated.append(SaveInfo(save_id, species.name or entry.name))
            found = True
        else:
            updated.append(entry)
    if not found:
        updated.append(SaveInfo(save_id, species.name or _default_name(updated)))
    _write_index(updated, save_id)


def create_new() -> tuple[str, Species]:
    """Новое существо по умолчанию, сразу становится текущим."""
    entries = list_saves()
    name = _default_name(entries)
    species = Species([default_blueprint()], name=name)
    save_id = _next_id(entries)
    species.save(_file_for(save_id))
    entries.append(SaveInfo(save_id, name))
    _write_index(entries, save_id)
    return save_id, species
