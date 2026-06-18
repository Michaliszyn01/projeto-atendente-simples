from typing import Any
from uuid import uuid4

from core.config.config_loader import carregar_config
from core.conversation.state import ConversationState
from core.scheduling.availability import tem_conflito
from core.storage.json_repository import JsonAgendaRepository


def criar_agendamento(
    state: ConversationState,
    repository: JsonAgendaRepository,
    config: dict[str, Any] | None = None,
) -> dict:
    config = config or carregar_config()
    if not all([state.nome, state.servico, state.data, state.horario, state.profissional]):
        raise ValueError("Não foi possível confirmar porque faltam dados do agendamento.")

    duracao = int(config["servicos"][state.servico])
    agenda = repository.listar()

    if tem_conflito(state.data, state.horario, state.profissional, duracao, agenda):
        raise ValueError("Esse horário acabou de ficar indisponível.")

    agendamento = {
        "id": str(uuid4()),
        "nome": state.nome,
        "servico": state.servico,
        "data": state.data,
        "horario": state.horario,
        "profissional": state.profissional,
        "duracao_minutos": duracao,
        "status": "agendado",
    }
    repository.adicionar(agendamento)
    return agendamento
