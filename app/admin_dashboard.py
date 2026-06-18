from datetime import date, timedelta
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:
    st = None

from core.admin import formatters, reports
from core.config.config_loader import carregar_config
from core.storage.json_repository import JsonAgendaRepository


def main() -> None:
    if st is None:
        raise RuntimeError("Streamlit não está instalado. Rode: pip install -r requirements.txt")

    st.set_page_config(page_title="Painel Administrativo", layout="wide")

    config = carregar_config()
    agenda_repository = JsonAgendaRepository()
    solicitacoes_repository = JsonAgendaRepository(reports.DEFAULT_SOLICITACOES_PATH)

    _mostrar_cabecalho(config)
    filtros = _sidebar(config)
    data_iso = filtros["data"].isoformat()

    resumo = reports.gerar_resumo_do_dia(data_iso, agenda_repository)
    solicitacoes = reports.listar_solicitacoes_loja(solicitacoes_repository)
    _mostrar_metricas(resumo, len(solicitacoes))

    abas = st.tabs(
        [
            "Visão geral",
            "Agenda",
            "Cancelados",
            "Horários disponíveis",
            "Solicitações",
            "Dados demo / Ajuda",
        ]
    )

    with abas[0]:
        _mostrar_visao_geral(resumo)

    with abas[1]:
        _mostrar_agenda(agenda_repository, data_iso, filtros["profissional"])

    with abas[2]:
        cancelados = reports.listar_agendamentos_cancelados(agenda_repository, data=data_iso)
        _mostrar_tabela(formatters.formatar_tabela_cancelados(cancelados))

    with abas[3]:
        _mostrar_horarios_disponiveis(agenda_repository, config, data_iso, filtros)

    with abas[4]:
        _mostrar_tabela(formatters.formatar_tabela_solicitacoes(solicitacoes))

    with abas[5]:
        _mostrar_ajuda_demo()


def _mostrar_cabecalho(config: dict[str, Any]) -> None:
    nome_estabelecimento = config.get("nome_estabelecimento", "Estabelecimento")
    st.title(f"Painel Administrativo - {nome_estabelecimento}")

    detalhes = [
        _cidade_estado(config),
        config.get("endereco", ""),
        config.get("telefone_estabelecimento", ""),
        config.get("instagram", ""),
    ]
    detalhes = [detalhe for detalhe in detalhes if detalhe]
    if detalhes:
        st.caption(" | ".join(detalhes))


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

    modo_demo = st.sidebar.checkbox("Estou usando dados demo")
    if modo_demo:
        st.sidebar.info("Para renovar a demonstração, rode: python scripts/gerar_dados_demo.py")

    _mostrar_divisor_sidebar()
    st.sidebar.subheader("Estabelecimento")
    dados = formatters.formatar_dados_estabelecimento(config)
    for campo, valor in dados.items():
        st.sidebar.caption(f"{campo}: {valor}")

    return {
        "data": data_selecionada,
        "profissional": profissional_filtro,
        "periodo": periodo,
        "servico": servico,
    }


def _mostrar_metricas(resumo: dict[str, Any], total_solicitacoes: int) -> None:
    colunas = st.columns(6)
    colunas[0].metric("Agendamentos no dia", resumo.get("total_agendamentos_ativos", 0))
    colunas[1].metric("Cancelamentos no dia", resumo.get("total_cancelados", 0))
    colunas[2].metric("Serviços no dia", sum(resumo.get("servicos", {}).values()))
    colunas[3].metric("Solicitações da loja", total_solicitacoes)
    colunas[4].metric("Profissional mais ocupado", resumo.get("profissional_mais_atendimentos") or "-")
    colunas[5].metric("Próximo horário", resumo.get("proximo_horario") or "-")


def _mostrar_visao_geral(resumo: dict[str, Any]) -> None:
    st.subheader("Resumo do dia")
    st.text(formatters.formatar_resumo_do_dia(resumo))

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Serviços mais marcados**")
        _mostrar_tabela(_formatar_contagem_tabela(resumo.get("servicos", {})))
    with colunas[1]:
        st.markdown("**Quantidade por profissional**")
        _mostrar_tabela(_formatar_contagem_tabela(resumo.get("por_profissional", {})))


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

    _mostrar_tabela(formatters.formatar_tabela_agendamentos(agendamentos))


def _mostrar_horarios_disponiveis(
    agenda_repository: JsonAgendaRepository,
    config: dict[str, Any],
    data_iso: str,
    filtros: dict[str, Any],
) -> None:
    st.write("Horários livres considerando os agendamentos ativos da data selecionada.")
    horarios = reports.listar_horarios_disponiveis(
        data=data_iso,
        periodo=filtros["periodo"],
        profissional=filtros["profissional"],
        agenda_repository=agenda_repository,
        config=config,
        servico=filtros["servico"],
    )

    for profissional, lista_horarios in horarios.items():
        st.markdown(f"**{profissional}**")
        st.write(", ".join(lista_horarios) if lista_horarios else "Sem horários livres.")

    if not horarios:
        st.info("Nenhum horário disponível.")


def _mostrar_ajuda_demo() -> None:
    st.subheader("Dados demo e operação local")
    st.write("O painel usa somente arquivos JSON locais. Ele ainda não possui IA, OpenAI ou WhatsApp real.")

    st.markdown("**Rodar atendimento no terminal**")
    st.code("python main.py", language="bash")

    st.markdown("**Rodar painel administrativo**")
    st.code("streamlit run app/admin_dashboard.py", language="bash")

    st.markdown("**Gerar dados fictícios para demonstração**")
    st.code("python scripts/gerar_dados_demo.py", language="bash")

    st.markdown("**Limpar agenda e solicitações locais**")
    st.code("python scripts/limpar_dados.py", language="bash")

    st.info("Atenção: data/agenda.json e data/solicitacoes.json podem conter dados reais. Não envie esses arquivos para o GitHub.")


def _mostrar_tabela(dados: list[dict] | str) -> None:
    if isinstance(dados, str):
        st.info(dados)
        return
    if not dados:
        st.info("Nenhum registro encontrado.")
        return
    st.dataframe(dados, use_container_width=True)


def _mostrar_divisor_sidebar() -> None:
    divisor = getattr(st.sidebar, "divider", None)
    if callable(divisor):
        divisor()
    else:
        st.sidebar.markdown("---")


def _formatar_contagem_tabela(contagem: dict | None) -> list[dict]:
    formatador = getattr(formatters, "formatar_contagem_tabela", None)
    if callable(formatador):
        return formatador(contagem)

    if not contagem:
        return []

    return [
        {"Item": item, "Quantidade": quantidade}
        for item, quantidade in sorted(
            contagem.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def _cidade_estado(config: dict[str, Any]) -> str:
    cidade = config.get("cidade", "")
    estado = config.get("estado", "")
    if cidade and estado:
        return f"{cidade} - {estado}"
    return cidade or estado


if __name__ == "__main__":
    main()
