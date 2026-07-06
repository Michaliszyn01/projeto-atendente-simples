from typing import Any

from core.config.config_loader import carregar_config
from core.scheduling.validators import horario_para_minutos, normalizar_texto


def calcular_horarios_disponiveis(
    data: str,
    servico: str,
    profissional_preferido: str | None,
    periodo: str,
    agenda: list[dict],
    config: dict[str, Any] | None = None,
    ignorar_agendamento_id: str | None = None,
) -> list[dict[str, str]]:
    config = config or carregar_config()
    duracao = int(config["servicos"][servico])
    profissionais = [profissional_preferido] if profissional_preferido else list(config.get("profissionais", []))
    periodo_config = resolver_periodo(periodo, config)
    horarios = list(config["horarios"][periodo_config])
    fim_periodo_minutos = calcular_fim_periodo_minutos(horarios, duracao)

    opcoes: list[dict[str, str]] = []
    for horario in horarios:
        inicio = horario_para_minutos(horario)
        fim = inicio + duracao

        if fim > fim_periodo_minutos:
            continue

        for profissional in profissionais:
            if not tem_conflito(
                data,
                horario,
                profissional,
                duracao,
                agenda,
                ignorar_agendamento_id=ignorar_agendamento_id,
            ):
                opcoes.append({"horario": horario, "profissional": profissional})

    return opcoes


def resolver_periodo(periodo: str, config: dict[str, Any]) -> str:
    if periodo in config.get("horarios", {}):
        return periodo
    periodo_normalizado = normalizar_texto(periodo)
    for chave in config.get("horarios", {}):
        if normalizar_texto(chave) == periodo_normalizado:
            return chave
    raise KeyError(periodo)


def calcular_fim_periodo_minutos(horarios: list[str], duracao_padrao: int) -> int:
    if not horarios:
        return 0
    minutos = [horario_para_minutos(horario) for horario in horarios]
    intervalos = [
        proximo - atual
        for atual, proximo in zip(minutos, minutos[1:])
        if proximo > atual
    ]
    intervalo = min(intervalos) if intervalos else duracao_padrao
    return minutos[-1] + intervalo


def tem_conflito(
    data: str,
    horario: str,
    profissional: str,
    duracao_minutos: int,
    agenda: list[dict],
    ignorar_agendamento_id: str | None = None,
) -> bool:
    inicio_novo = horario_para_minutos(horario)
    fim_novo = inicio_novo + duracao_minutos

    for agendamento in agenda:
        if ignorar_agendamento_id is not None and agendamento.get("id") == ignorar_agendamento_id:
            continue
        if agendamento.get("status") == "cancelado":
            continue
        if agendamento.get("data") != data:
            continue
        if agendamento.get("profissional") != profissional:
            continue

        inicio_existente = horario_para_minutos(agendamento["horario"])
        duracao_existente = int(agendamento.get("duracao_minutos", 30))
        fim_existente = inicio_existente + duracao_existente

        if intervalos_sobrepoem(inicio_novo, fim_novo, inicio_existente, fim_existente):
            return True

    return False


def intervalos_sobrepoem(
    inicio_a: int,
    fim_a: int,
    inicio_b: int,
    fim_b: int,
) -> bool:
    return inicio_a < fim_b and inicio_b < fim_a
