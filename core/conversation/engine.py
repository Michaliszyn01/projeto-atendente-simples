from datetime import date
from typing import Any

from core.config.config_loader import carregar_config
from core.conversation.flow import AtendimentoFlow
from core.conversation.session_store import InMemorySessionStore
from core.conversation.state import ConversationState
from core.storage.json_repository import JsonAgendaRepository


class ConversationEngine:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        agenda_repository: JsonAgendaRepository | None = None,
        solicitacao_repository: JsonAgendaRepository | None = None,
        session_store: InMemorySessionStore | None = None,
        hoje: date | None = None,
    ) -> None:
        self.config = config or carregar_config()
        self.agenda_repository = agenda_repository or JsonAgendaRepository()
        self.solicitacao_repository = solicitacao_repository
        self.session_store = session_store or InMemorySessionStore()
        self.hoje = hoje

    def start(self, session_id: str) -> str:
        flow = self._new_flow()
        resposta = flow.iniciar()
        self.session_store.save(session_id, flow.state, finished=flow.encerrado)
        return resposta

    def process_message(self, session_id: str, message: str) -> str:
        if not self.session_store.exists(session_id):
            self.session_store.save(session_id, ConversationState(etapa="escolha_inicial"))

        flow = self._flow_for_session(session_id)
        resposta = flow.receber(message)
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
        flow.encerrado = self.session_store.is_finished(session_id)
        return flow
