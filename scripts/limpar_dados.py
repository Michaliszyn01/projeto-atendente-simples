import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.storage.json_repository import DEFAULT_AGENDA_PATH


DEFAULT_SOLICITACOES_PATH = PROJECT_ROOT / "data" / "solicitacoes.json"


def limpar_dados(
    agenda_path: str | Path = DEFAULT_AGENDA_PATH,
    solicitacoes_path: str | Path = DEFAULT_SOLICITACOES_PATH,
) -> None:
    _salvar_lista_vazia(Path(agenda_path))
    _salvar_lista_vazia(Path(solicitacoes_path))


def _salvar_lista_vazia(caminho: Path) -> None:
    if not caminho.is_absolute():
        caminho = PROJECT_ROOT / caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    limpar_dados()
    print("Dados locais limpos com sucesso.")


if __name__ == "__main__":
    main()
