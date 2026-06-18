import json
from pathlib import Path

from core.scheduling.validators import normalizar_telefone


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

    def listar_agendamentos(self) -> list[dict]:
        return self.listar()

    def salvar(self, agenda: list[dict]) -> None:
        self._garantir_arquivo()
        self.caminho.write_text(
            json.dumps(agenda, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def salvar_agendamentos(self, agenda: list[dict]) -> None:
        self.salvar(agenda)

    def adicionar(self, agendamento: dict) -> None:
        agenda = self.listar()
        agenda.append(agendamento)
        self.salvar(agenda)

    def adicionar_agendamento(self, agendamento: dict) -> None:
        self.adicionar(agendamento)

    def buscar_agendamentos_por_telefone(
        self,
        telefone: str,
        apenas_ativos: bool = True,
    ) -> list[dict]:
        telefone_normalizado = normalizar_telefone(telefone)
        encontrados = []

        for agendamento in self.listar():
            if normalizar_telefone(str(agendamento.get("telefone", ""))) != telefone_normalizado:
                continue
            if apenas_ativos and agendamento.get("status") != "agendado":
                continue
            encontrados.append(agendamento)

        return encontrados

    def atualizar_agendamento(self, agendamento_id: str, dados_atualizados: dict) -> dict | None:
        agenda = self.listar()
        for indice, agendamento in enumerate(agenda):
            if agendamento.get("id") == agendamento_id:
                agenda[indice] = {**agendamento, **dados_atualizados}
                self.salvar(agenda)
                return agenda[indice]
        return None

    def _garantir_arquivo(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        if not self.caminho.exists():
            self.caminho.write_text("[]", encoding="utf-8")
