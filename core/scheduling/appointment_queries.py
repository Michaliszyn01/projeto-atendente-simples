from typing import Any

from core.scheduling.validators import normalizar_telefone


def buscar_agendamentos_ativos_por_telefone(
    repository: Any,
    telefone: str,
) -> list[dict]:
    return repository.buscar_agendamentos_por_telefone(
        normalizar_telefone(telefone),
        apenas_ativos=True,
    )


def cancelar_agendamento(
    repository: Any,
    agendamento_id: str,
) -> dict | None:
    return repository.cancelar_agendamento(agendamento_id)


def remarcar_agendamento(
    repository: Any,
    agendamento_id: str,
    nova_data: str,
    novo_horario: str,
    profissional: str,
) -> dict | None:
    return repository.remarcar_agendamento(
        agendamento_id,
        nova_data,
        novo_horario,
        profissional,
    )
