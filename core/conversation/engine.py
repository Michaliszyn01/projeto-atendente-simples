from datetime import date
from typing import Any
from collections import defaultdict

from core.config.config_loader import carregar_config
from core.conversation.flow import AtendimentoFlow
from core.conversation.session_store import InMemorySessionStore
from core.conversation.state import ConversationState
from core.scheduling.validators import normalizar_telefone_whatsapp
from core.storage.repository_factory import criar_agenda_repository
from core.storage.sqlite_repository import SQLiteAgendaRepository, SQLiteSessionStore


class ConversationEngine:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        agenda_repository: Any | None = None,
        solicitacao_repository: Any | None = None,
        session_store: Any | None = None,
        hoje: date | None = None,
    ) -> None:
        self.config = config or carregar_config()
        self.agenda_repository = agenda_repository or criar_agenda_repository(self.config)
        self.solicitacao_repository = solicitacao_repository
        if session_store is not None:
            self.session_store = session_store
        elif isinstance(self.agenda_repository, SQLiteAgendaRepository):
            self.session_store = SQLiteSessionStore(self.agenda_repository.caminho)
        else:
            self.session_store = InMemorySessionStore()
        self.hoje = hoje

    def start(self, session_id: str) -> str:
        flow = self._new_flow()
        resposta = flow.iniciar()
        self._preencher_telefone_detectado(session_id, flow.state)
        flow.state.boas_vindas_enviada = True
        self.session_store.save(session_id, flow.state, finished=flow.encerrado)
        return resposta

    def process_message(self, session_id: str, message: str) -> str:
        if not self.session_store.exists(session_id):
            state = ConversationState(etapa="escolha_inicial")
            self._preencher_telefone_detectado(session_id, state)
            self.session_store.save(session_id, state)

        flow = self._flow_for_session(session_id)
        enviar_boas_vindas = self._deve_enviar_boas_vindas(session_id, flow.state)
        resposta = flow.receber(message)
        if enviar_boas_vindas:
            flow.state.boas_vindas_enviada = True
            resposta = self._combinar_boas_vindas(resposta)
        self.session_store.save(session_id, flow.state, finished=flow.encerrado)
        return resposta

    def processar_mensagem(self, session_id: str, mensagem: str) -> str:
        return self.process_message(session_id, mensagem)

    def is_finished(self, session_id: str) -> bool:
        return self.session_store.is_finished(session_id)

    def reset(self, session_id: str) -> str:
        self.session_store.reset(session_id)
        return self.start(session_id)

    def delete_session(self, session_id: str) -> None:
        self.session_store.delete(session_id)

    def _new_flow(self) -> AtendimentoFlow:
        return AtendimentoFlow(
            self.agenda_repository,
            hoje=self.hoje,
            config=self.config,
            solicitacoes_repository=self.solicitacao_repository,
        )

    def _flow_for_session(self, session_id: str) -> AtendimentoFlow:
        flow = self._new_flow()
        flow.state = self.session_store.get_or_create(session_id)
        self._preencher_telefone_detectado(session_id, flow.state)
        flow.encerrado = self.session_store.is_finished(session_id)
        return flow

    def _preencher_telefone_detectado(self, session_id: str, state: ConversationState) -> None:
        if state.telefone:
            return

        telefone = self._telefone_do_session_id(session_id)
        if telefone is not None:
            state.telefone = telefone

    def _deve_enviar_boas_vindas(self, session_id: str, state: ConversationState) -> bool:
        return self._telefone_do_session_id(session_id) is not None and deve_enviar_boas_vindas(state)

    def _combinar_boas_vindas(self, resposta: str) -> str:
        boas_vindas = montar_mensagem_boas_vindas(self.config)
        if not resposta:
            return boas_vindas
        return f"{boas_vindas}\n\n{resposta}"

    def _telefone_do_session_id(self, session_id: str) -> str | None:
        try:
            return normalizar_telefone_whatsapp(session_id)
        except ValueError:
            return None


def deve_enviar_boas_vindas(state: ConversationState) -> bool:
    return not state.boas_vindas_enviada


def montar_mensagem_boas_vindas(config: dict[str, Any]) -> str:
    mensagem_configurada = str(config.get("mensagens", {}).get("boas_vindas", "")).strip()
    if mensagem_configurada:
        contexto = defaultdict(str, config)
        return mensagem_configurada.format_map(contexto)

    nome = str(config.get("nome_estabelecimento") or "atendimento automatico").strip()
    opcoes = config.get("opcoes_inicio") or [
        "agendar",
        "consultar",
        "cancelar",
        "remarcar",
        "falar com uma pessoa",
    ]
    linhas = [f"{indice}. {opcao}" for indice, opcao in enumerate(opcoes, start=1)]
    return (
        f"Ola! Seja bem-vindo ao atendimento automatico da {nome}.\n\n"
        "Por aqui voce pode:\n\n"
        f"{chr(10).join(linhas)}\n\n"
        "Digite uma das opcoes acima para continuar."
    )
