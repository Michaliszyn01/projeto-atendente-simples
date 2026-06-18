from core.scheduling.validators import normalizar_telefone
from core.storage.json_repository import JsonAgendaRepository


def buscar_agendamentos_ativos_por_telefone(
    repository: JsonAgendaRepository,
    telefone: str,
) -> list[dict]:
    return repository.buscar_agendamentos_por_telefone(
        normalizar_telefone(telefone),
        apenas_ativos=True,
    )


def atualizar_status_agendamento(
    repository: JsonAgendaRepository,
    agendamento_id: str,
    status: str,
    extras: dict | None = None,
) -> dict | None:
    dados = {"status": status}
    if extras:
        dados.update(extras)
    return repository.atualizar_agendamento(agendamento_id, dados)
