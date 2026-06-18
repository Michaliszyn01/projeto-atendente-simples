import json
from pathlib import Path
from datetime import datetime

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

    def buscar_agendamentos_ativos_por_telefone(self, telefone: str) -> list[dict]:
        return self.buscar_agendamentos_por_telefone(telefone, apenas_ativos=True)

    def buscar_agendamento_por_id(self, agendamento_id: str) -> dict | None:
        for agendamento in self.listar():
            if agendamento.get("id") == agendamento_id:
                return agendamento
        return None

    def atualizar_agendamento(self, agendamento_id: str, dados_atualizados: dict) -> dict | None:
        agenda = self.listar()
        for indice, agendamento in enumerate(agenda):
            if agendamento.get("id") == agendamento_id:
                agenda[indice] = {**agendamento, **dados_atualizados}
                self.salvar(agenda)
                return agenda[indice]
        return None

    def cancelar_agendamento(self, agendamento_id: str) -> dict | None:
        feito_em = self._agora()
        agendamento = self.buscar_agendamento_por_id(agendamento_id)
        if agendamento is None:
            return None

        return self.atualizar_agendamento(
            agendamento_id,
            {
                "status": "cancelado",
                "cancelado_em": feito_em,
                "historico": self._historico_com_evento(
                    agendamento,
                    {"acao": "cancelado", "feito_em": feito_em},
                ),
            },
        )

    def remarcar_agendamento(
        self,
        agendamento_id: str,
        nova_data: str,
        novo_horario: str,
        profissional: str,
    ) -> dict | None:
        feito_em = self._agora()
        agendamento = self.buscar_agendamento_por_id(agendamento_id)
        if agendamento is None:
            return None

        evento = {
            "acao": "remarcado",
            "data_anterior": agendamento.get("data"),
            "horario_anterior": agendamento.get("horario"),
            "profissional_anterior": agendamento.get("profissional"),
            "data_nova": nova_data,
            "horario_novo": novo_horario,
            "profissional_novo": profissional,
            "feito_em": feito_em,
        }

        return self.atualizar_agendamento(
            agendamento_id,
            {
                "data": nova_data,
                "horario": novo_horario,
                "profissional": profissional,
                "status": "agendado",
                "remarcado_em": feito_em,
                "historico": self._historico_com_evento(agendamento, evento),
            },
        )

    def _agora(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _historico_com_evento(self, agendamento: dict, evento: dict) -> list[dict]:
        historico = list(agendamento.get("historico", []))
        historico.append(evento)
        return historico

    def _garantir_arquivo(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        if not self.caminho.exists():
            self.caminho.write_text("[]", encoding="utf-8")
