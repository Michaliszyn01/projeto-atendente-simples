import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.storage.sqlite_repository import DEFAULT_DB_PATH, SQLiteAgendaRepository, SQLiteSessionStore


DEFAULT_SOLICITACOES_PATH = PROJECT_ROOT / "data" / "solicitacoes.json"


def limpar_dados(
    agenda_path: str | Path | None = None,
    solicitacoes_path: str | Path = DEFAULT_SOLICITACOES_PATH,
) -> None:
    _limpar_agenda(agenda_path)
    _salvar_lista_vazia(Path(solicitacoes_path))


def _salvar_lista_vazia(caminho: Path) -> None:
    if not caminho.is_absolute():
        caminho = PROJECT_ROOT / caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")


def _limpar_agenda(caminho: str | Path | None) -> None:
    if caminho is None:
        SQLiteAgendaRepository(DEFAULT_DB_PATH).limpar()
        SQLiteSessionStore(DEFAULT_DB_PATH).clear()
        return

    caminho_path = Path(caminho)
    if caminho_path.suffix.lower() == ".json":
        _salvar_lista_vazia(caminho_path)
        return

    SQLiteAgendaRepository(caminho_path).limpar()
    SQLiteSessionStore(caminho_path).clear()


def main() -> None:
    limpar_dados()
    print("Dados locais limpos com sucesso.")


if __name__ == "__main__":
    main()
