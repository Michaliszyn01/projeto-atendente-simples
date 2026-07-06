from pathlib import Path
from typing import Any

from core.storage.json_repository import JsonAgendaRepository
from core.storage.sqlite_repository import DEFAULT_DB_PATH, SQLiteAgendaRepository


def criar_agenda_repository(
    config: dict[str, Any] | None = None,
    caminho: str | Path | None = None,
) -> JsonAgendaRepository | SQLiteAgendaRepository:
    if caminho is not None:
        caminho_path = Path(caminho)
        if caminho_path.suffix.lower() == ".json":
            return JsonAgendaRepository(caminho_path)
        return SQLiteAgendaRepository(caminho_path)

    storage = (config or {}).get("storage", {})
    if not isinstance(storage, dict):
        storage = {}

    tipo = str(storage.get("type", "sqlite")).strip().lower()
    storage_path = storage.get("path")

    if tipo == "json":
        return JsonAgendaRepository(storage_path)

    return SQLiteAgendaRepository(storage_path or DEFAULT_DB_PATH)
