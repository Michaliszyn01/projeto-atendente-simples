from datetime import date, timedelta
from typing import Any

import streamlit as st

from core.admin import formatters, reports
from core.config.config_loader import carregar_config
from core.storage.json_repository import JsonAgendaRepository


def main() -> None:
    st.set_page_config(page_title="Painel Administrativo", layout="wide")

    config = carregar_config()
    agenda_repository = JsonAgendaRepository()
    solicitacoes_repository = JsonAgendaRepository(reports.DEFAULT_SOLICITACOES_PATH)

    nome_estabelecimento = config.get("nome_estabelecimento", "Estabelecimento")
    st.title(f"Painel Administrativo - {nome_estabelecimento}")
    _mostrar_dados_estabelecimento(config)

    filtros = _sidebar(config)
    data_iso = filtros["data"].isoformat()

    resumo = reports.gerar_resumo_do_dia(data_iso, agenda_repository)
    _mostrar_metricas(resumo)

    aba_agenda, aba_cancelados, aba_solicitacoes, aba_horarios, aba_resumo = st.tabs(
        ["Agenda", "Cancelados", "Solicitações", "Horários disponíveis", "Resumo do dia"]
    )

    with aba_agenda:
        _mostrar_agenda(agenda_repository, data_iso, filtros["profissional"])

    with aba_cancelados:
        cancelados = reports.listar_agendamentos_cancelados(agenda_repository, data=data_iso)
        _mostrar_tabela(formatters.formatar_lista_cancelados(cancelados))

    with aba_solicitacoes:
        solicitacoes = reports.listar_solicitacoes_loja(solicitacoes_repository)
        _mostrar_tabela(formatters.formatar_solicitacoes(solicitacoes))

    with aba_horarios:
        horarios = reports.listar_horarios_disponiveis(
            data=data_iso,
            periodo=filtros["periodo"],
            profissional=filtros["profissional"],
            agenda_repository=agenda_repository,
            config=config,
            servico=filtros["servico"],
        )
        _mostrar_tabela(formatters.formatar_horarios_disponiveis(horarios))

    with aba_resumo:
        st.text(formatters.formatar_resumo_do_dia(resumo))


def _sidebar(config: dict[str, Any]) -> dict[str, Any]:
    st.sidebar.header("Filtros")
    atalho_data = st.sidebar.selectbox("Agenda", ["Hoje", "Amanhã", "Escolher data"])
    if atalho_data == "Hoje":
        data_selecionada = date.today()
    elif atalho_data == "Amanhã":
        data_selecionada = date.today() + timedelta(days=1)
    else:
        data_selecionada = st.sidebar.date_input("Data", value=date.today())

    profissionais = ["Todos"] + list(config.get("profissionais", []))
    profissional = st.sidebar.selectbox("Profissional", profissionais)
    profissional_filtro = None if profissional == "Todos" else profissional

    periodos = list(config.get("horarios", {}).keys()) or ["manha", "tarde"]
    periodo = st.sidebar.selectbox("Período", periodos)

    servicos = list(config.get("servicos", {}).keys())
    servico = st.sidebar.selectbox("Serviço", servicos) if servicos else None

    st.sidebar.caption(f"Hoje: {date.today().strftime('%d/%m/%Y')}")
    st.sidebar.caption(f"Amanhã: {(date.today() + timedelta(days=1)).strftime('%d/%m/%Y')}")

    return {
        "data": data_selecionada,
        "profissional": profissional_filtro,
        "periodo": periodo,
        "servico": servico,
    }


def _mostrar_dados_estabelecimento(config: dict[str, Any]) -> None:
    dados = formatters.formatar_dados_estabelecimento(config)
    if not dados:
        return

    texto = " | ".join(f"{campo}: {valor}" for campo, valor in dados.items())
    st.caption(texto)


def _mostrar_metricas(resumo: dict[str, Any]) -> None:
    colunas = st.columns(4)
    colunas[0].metric("Agendamentos no dia", resumo.get("total_agendamentos_ativos", 0))
    colunas[1].metric("Cancelamentos no dia", resumo.get("total_cancelados", 0))
    colunas[2].metric("Total de serviços no dia", sum(resumo.get("servicos", {}).values()))
    colunas[3].metric("Profissional destaque", resumo.get("profissional_mais_atendimentos") or "-")


def _mostrar_agenda(
    agenda_repository: JsonAgendaRepository,
    data_iso: str,
    profissional: str | None,
) -> None:
    if profissional:
        agendamentos = reports.listar_agendamentos_por_profissional(
            profissional,
            agenda_repository,
            data=data_iso,
        )
    else:
        agendamentos = reports.listar_agendamentos_por_data(data_iso, agenda_repository)

    _mostrar_tabela(formatters.formatar_lista_agendamentos(agendamentos))


def _mostrar_tabela(dados: list[dict[str, str]] | str) -> None:
    if isinstance(dados, str):
        st.info(dados)
        return
    st.dataframe(dados, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
