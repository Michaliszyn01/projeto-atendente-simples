from datetime import datetime
from typing import Any
from uuid import uuid4

from core.config.config_loader import carregar_config
from core.conversation.state import ConversationState
from core.scheduling.availability import tem_conflito
from core.scheduling.validators import normalizar_telefone_whatsapp


def criar_agendamento(
    state: ConversationState,
    repository: Any,
    config: dict[str, Any] | None = None,
) -> dict:
    config = config or carregar_config()
    if not all([state.nome, state.telefone, state.servico, state.data, state.horario, state.profissional]):
        raise ValueError("Não foi possível confirmar porque faltam dados do agendamento.")

    duracao = int(config["servicos"][state.servico])
    agenda = repository.listar()

    if tem_conflito(state.data, state.horario, state.profissional, duracao, agenda):
        raise ValueError("Esse horário acabou de ficar indisponível.")

    criado_em = datetime.now().isoformat(timespec="seconds")
    telefone_normalizado = _normalizar_telefone_para_cliente(state.telefone)

    agendamento = {
        "id": str(uuid4()),
        "cliente_id": telefone_normalizado,
        "nome": state.nome,
        "telefone": state.telefone,
        "telefone_normalizado": telefone_normalizado,
        "servico": state.servico,
        "data": state.data,
        "horario": state.horario,
        "profissional": state.profissional,
        "duracao_minutos": duracao,
        "status": "agendado",
        "criado_em": criado_em,
        "atualizado_em": criado_em,
        "origem": "whatsapp",
    }
    repository.adicionar_agendamento(agendamento)
    return agendamento


def _normalizar_telefone_para_cliente(telefone: str | None) -> str:
    try:
        return normalizar_telefone_whatsapp(telefone or "")
    except ValueError:
        return telefone or "terminal_demo"
