from pathlib import Path

from core.storage.json_repository import DEFAULT_AGENDA_PATH, JsonAgendaRepository
from core.storage.sqlite_repository import DEFAULT_DB_PATH, SQLiteAgendaRepository


def migrar_json_para_sqlite(
    json_path: str | Path = DEFAULT_AGENDA_PATH,
    sqlite_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, int | str]:
    origem = Path(json_path)
    if not origem.is_absolute():
        origem = DEFAULT_AGENDA_PATH.parents[1] / origem

    destino = Path(sqlite_path)
    if not destino.is_absolute():
        destino = DEFAULT_DB_PATH.parents[1] / destino

    if not origem.exists():
        return {
            "origem": str(origem),
            "destino": str(destino),
            "lidos": 0,
            "novos": 0,
            "total_sqlite": len(SQLiteAgendaRepository(destino).listar()),
        }

    json_repository = JsonAgendaRepository(origem)
    sqlite_repository = SQLiteAgendaRepository(destino)
    dados_json = json_repository.listar()
    ids_antes = {item.get("id") for item in sqlite_repository.listar() if item.get("id")}

    for indice, agendamento in enumerate(dados_json, start=1):
        item = dict(agendamento)
        item.setdefault("id", f"migrado-json-{indice}")
        sqlite_repository.adicionar_agendamento(item)

    agenda_sqlite = sqlite_repository.listar()
    ids_depois = {item.get("id") for item in agenda_sqlite if item.get("id")}

    return {
        "origem": str(origem),
        "destino": str(destino),
        "lidos": len(dados_json),
        "novos": len(ids_depois - ids_antes),
        "total_sqlite": len(agenda_sqlite),
    }


def main() -> None:
    resumo = migrar_json_para_sqlite()
    print(
        "Migracao concluida: "
        f"{resumo['lidos']} registro(s) lidos, "
        f"{resumo['novos']} novo(s), "
        f"{resumo['total_sqlite']} no SQLite."
    )


if __name__ == "__main__":
    main()
