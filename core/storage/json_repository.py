import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENDA_PATH = PROJECT_ROOT / "data" / "agenda.json"


class JsonAgendaRepository:
    def __init__(self, caminho: str | Path | None = None) -> None:
        self.caminho = Path(caminho) if caminho is not None else DEFAULT_AGENDA_PATH
        if not self.caminho.is_absolute():
            self.caminho = PROJECT_ROOT / self.caminho
        self._garantir_arquivo()

    def listar(self) -> list[dict]:
        self._garantir_arquivo()
        conteudo = self.caminho.read_text(encoding="utf-8").strip()

        if not conteudo:
            self.salvar([])
            return []

        try:
            dados = json.loads(conteudo)
        except json.JSONDecodeError:
            self.salvar([])
            return []

        if not isinstance(dados, list):
            self.salvar([])
            return []
        return dados

    def salvar(self, agenda: list[dict]) -> None:
        self._garantir_arquivo()
        self.caminho.write_text(
            json.dumps(agenda, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def adicionar(self, agendamento: dict) -> None:
        agenda = self.listar()
        agenda.append(agendamento)
        self.salvar(agenda)

    def _garantir_arquivo(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        if not self.caminho.exists():
            self.caminho.write_text("[]", encoding="utf-8")
