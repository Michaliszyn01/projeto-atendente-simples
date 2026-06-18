from collections import Counter
from datetime import date, timedelta
from typing import Any

from core.config.config_loader import carregar_config
from core.scheduling.availability import calcular_horarios_disponiveis
from core.storage.json_repository import JsonAgendaRepository


DEFAULT_SOLICITACOES_PATH = "data/solicitacoes.json"


def listar_agendamentos_por_data(
    data: str,
    agenda_repository: JsonAgendaRepository | None = None,
) -> list[dict]:
    agenda = _listar_agenda(agenda_repository)
    return _ordenar_agendamentos(
        agendamento
        for agendamento in agenda
        if agendamento.get("data") == data and agendamento.get("status") == "agendado"
    )


def listar_agendamentos_hoje(
    agenda_repository: JsonAgendaRepository | None = None,
    hoje: date | None = None,
) -> list[dict]:
    hoje = hoje or date.today()
    return listar_agendamentos_por_data(hoje.isoformat(), agenda_repository)


def listar_agendamentos_amanha(
    agenda_repository: JsonAgendaRepository | None = None,
    hoje: date | None = None,
) -> list[dict]:
    hoje = hoje or date.today()
    return listar_agendamentos_por_data((hoje + timedelta(days=1)).isoformat(), agenda_repository)


def listar_agendamentos_por_profissional(
    profissional: str,
    agenda_repository: JsonAgendaRepository | None = None,
    data: str | None = None,
) -> list[dict]:
    agenda = _listar_agenda(agenda_repository)
    return _ordenar_agendamentos(
        agendamento
        for agendamento in agenda
        if agendamento.get("status") == "agendado"
        and agendamento.get("profissional") == profissional
        and (data is None or agendamento.get("data") == data)
    )


def listar_agendamentos_cancelados(
    agenda_repository: JsonAgendaRepository | None = None,
    data: str | None = None,
) -> list[dict]:
    agenda = _listar_agenda(agenda_repository)
    return _ordenar_agendamentos(
        agendamento
        for agendamento in agenda
        if agendamento.get("status") == "cancelado"
        and (data is None or agendamento.get("data") == data)
    )


def listar_solicitacoes_loja(
    solicitacoes_repository: JsonAgendaRepository | None = None,
) -> list[dict]:
    repository = solicitacoes_repository or JsonAgendaRepository(DEFAULT_SOLICITACOES_PATH)
    return list(repository.listar())


def gerar_resumo_do_dia(
    data: str,
    agenda_repository: JsonAgendaRepository | None = None,
) -> dict[str, Any]:
    ativos = listar_agendamentos_por_data(data, agenda_repository)
    cancelados = listar_agendamentos_cancelados(agenda_repository, data=data)
    horarios = sorted(str(agendamento.get("horario", "")) for agendamento in ativos if agendamento.get("horario"))
    por_profissional = Counter(str(agendamento.get("profissional", "")) for agendamento in ativos)
    por_profissional.pop("", None)

    return {
        "data": data,
        "total_agendamentos_ativos": len(ativos),
        "total_cancelados": len(cancelados),
        "servicos": dict(Counter(str(agendamento.get("servico", "")) for agendamento in ativos)),
        "por_profissional": dict(por_profissional),
        "primeiro_horario": horarios[0] if horarios else None,
        "ultimo_horario": horarios[-1] if horarios else None,
        "profissional_mais_atendimentos": _item_mais_comum(por_profissional),
    }


def listar_horarios_disponiveis(
    data: str,
    periodo: str,
    profissional: str | None = None,
    agenda_repository: JsonAgendaRepository | None = None,
    config: dict[str, Any] | None = None,
    servico: str | None = None,
) -> dict[str, list[str]]:
    config = config or carregar_config()
    servico = servico or _primeiro_servico(config)
    if servico is None or not config.get("usa_agendamento", False):
        return {}

    agenda = _listar_agenda(agenda_repository)
    profissional_preferido = None if _todos_os_profissionais(profissional) else profissional
    opcoes = calcular_horarios_disponiveis(
        data=data,
        servico=servico,
        profissional_preferido=profissional_preferido,
        periodo=periodo,
        agenda=agenda,
        config=config,
    )

    horarios_por_profissional: dict[str, list[str]] = {}
    for opcao in opcoes:
        nome_profissional = opcao["profissional"]
        horarios_por_profissional.setdefault(nome_profissional, []).append(opcao["horario"])

    return {
        nome_profissional: sorted(horarios)
        for nome_profissional, horarios in sorted(horarios_por_profissional.items())
    }


def _listar_agenda(agenda_repository: JsonAgendaRepository | None) -> list[dict]:
    repository = agenda_repository or JsonAgendaRepository()
    return repository.listar()


def _ordenar_agendamentos(agendamentos) -> list[dict]:
    return sorted(
        list(agendamentos),
        key=lambda agendamento: (
            str(agendamento.get("data", "")),
            str(agendamento.get("horario", "")),
            str(agendamento.get("profissional", "")),
            str(agendamento.get("nome", "")),
        ),
    )


def _primeiro_servico(config: dict[str, Any]) -> str | None:
    servicos = config.get("servicos", {})
    if not isinstance(servicos, dict) or not servicos:
        return None
    return next(iter(servicos))


def _todos_os_profissionais(profissional: str | None) -> bool:
    return profissional is None or profissional.strip().lower() in {"", "todos", "todas"}


def _item_mais_comum(contador: Counter) -> str | None:
    if not contador:
        return None
    return contador.most_common(1)[0][0]

