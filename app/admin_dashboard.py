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
    agenda = agenda_repository.listar()
    solicitacoes = reports.listar_solicitacoes_loja(solicitacoes_repository)

    _mostrar_cabecalho(config)
    filtros = _sidebar(config, agenda)
    data_iso = filtros["data"].isoformat()

    resumo = reports.gerar_resumo_do_dia(data_iso, agenda_repository)
    agendamentos_filtrados = _filtrar_agendamentos(agenda, data_iso, filtros)
    proximos = _proximos_agendamentos(agenda, filtros)
    cancelados = _filtrar_cancelados(agenda, data_iso, filtros)
    remarcados = _filtrar_remarcados(agenda, data_iso, filtros)

    _mostrar_metricas(resumo, len(solicitacoes), proximos, remarcados)

    abas = st.tabs(
        [
            "Visão geral",
            "Agenda do dia",
            "Próximos",
            "Cancelamentos",
            "Remarcações",
            "Horários disponíveis",
            "Solicitações",
            "Dados demo / Ajuda",
        ]
    )

    with abas[0]:
        _mostrar_visao_geral(resumo, agendamentos_filtrados, proximos, cancelados, remarcados)

    with abas[1]:
        st.subheader("Agenda do dia")
        _mostrar_tabela(_formatar_agendamentos_painel(agendamentos_filtrados))

    with abas[2]:
        st.subheader("Próximos agendamentos")
        _mostrar_tabela(_formatar_agendamentos_painel(proximos))

    with abas[3]:
        st.subheader("Resumo de cancelamentos")
        _mostrar_tabela(_formatar_agendamentos_painel(cancelados))

    with abas[4]:
        st.subheader("Resumo de remarcações")
        _mostrar_tabela(_formatar_agendamentos_painel(remarcados))

    with abas[5]:
        _mostrar_horarios_disponiveis(agenda_repository, config, data_iso, filtros)

    with abas[6]:
        st.subheader("Solicitações da loja")
        _mostrar_tabela(formatters.formatar_tabela_solicitacoes(solicitacoes))

    with abas[7]:
        _mostrar_ajuda_demo()


def _mostrar_cabecalho(config: dict[str, Any]) -> None:
    nome_estabelecimento = config.get("nome_estabelecimento", "Estabelecimento")
    st.title(f"Painel de Operação - {nome_estabelecimento}")
    st.caption("Painel local de demonstração para acompanhar agenda, atendimentos e solicitações.")

    detalhes = [
        _cidade_estado(config),
        config.get("endereco", ""),
        config.get("telefone_estabelecimento", ""),
        config.get("instagram", ""),
    ]
    detalhes = [detalhe for detalhe in detalhes if detalhe]
    if detalhes:
        st.caption(" | ".join(detalhes))


def _sidebar(config: dict[str, Any], agenda: list[dict]) -> dict[str, Any]:
    st.sidebar.header("Filtros da demonstração")
    atalho_data = st.sidebar.selectbox("Agenda", ["Hoje", "Amanhã", "Escolher data"])
    if atalho_data == "Hoje":
        data_selecionada = date.today()
    elif atalho_data == "Amanhã":
        data_selecionada = date.today() + timedelta(days=1)
    else:
        data_selecionada = st.sidebar.date_input("Data", value=date.today())

    status = st.sidebar.selectbox("Status", ["Todos", "Agendado", "Cancelado", "Remarcado"])

    servicos = _opcoes_unicas(config.get("servicos", {}).keys(), (item.get("servico") for item in agenda))
    servico = st.sidebar.selectbox("Serviço", ["Todos"] + servicos) if servicos else "Todos"

    profissionais = _opcoes_unicas(config.get("profissionais", []), (item.get("profissional") for item in agenda))
    profissional = st.sidebar.selectbox("Profissional", ["Todos"] + profissionais) if profissionais else "Todos"

    periodos = list(config.get("horarios", {}).keys()) or ["manha", "tarde"]
    periodo = st.sidebar.selectbox("Período para horários livres", periodos)

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
        "status": None if status == "Todos" else status.lower(),
        "servico": None if servico == "Todos" else servico,
        "profissional": None if profissional == "Todos" else profissional,
        "periodo": periodo,
    }


def _mostrar_metricas(
    resumo: dict[str, Any],
    total_solicitacoes: int,
    proximos: list[dict],
    remarcados: list[dict],
) -> None:
    colunas = st.columns(6)
    colunas[0].metric("Agendamentos no dia", resumo.get("total_agendamentos_ativos", 0))
    colunas[1].metric("Cancelamentos no dia", resumo.get("total_cancelados", 0))
    colunas[2].metric("Serviços no dia", sum(resumo.get("servicos", {}).values()))
    colunas[3].metric("Solicitações da loja", total_solicitacoes)
    colunas[4].metric("Remarcações no dia", len(remarcados))
    colunas[5].metric("Próximo horário", _proximo_horario(proximos) or "-")


def _mostrar_visao_geral(
    resumo: dict[str, Any],
    agendamentos: list[dict],
    proximos: list[dict],
    cancelados: list[dict],
    remarcados: list[dict],
) -> None:
    st.subheader("Visão geral da operação")
    st.write(formatters.formatar_resumo_do_dia(resumo))

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Serviços mais marcados**")
        _mostrar_tabela(_formatar_contagem_tabela(resumo.get("servicos", {})))
    with colunas[1]:
        st.markdown("**Quantidade por profissional**")
        _mostrar_tabela(_formatar_contagem_tabela(resumo.get("por_profissional", {})))

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Agenda do dia**")
        _mostrar_tabela(_formatar_agendamentos_painel(agendamentos[:5]))
    with colunas[1]:
        st.markdown("**Próximos agendamentos**")
        _mostrar_tabela(_formatar_agendamentos_painel(proximos[:5]))

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Cancelamentos**")
        _mostrar_tabela(_formatar_agendamentos_painel(cancelados[:5]))
    with colunas[1]:
        st.markdown("**Remarcações**")
        _mostrar_tabela(_formatar_agendamentos_painel(remarcados[:5]))


def _mostrar_horarios_disponiveis(
    agenda_repository: JsonAgendaRepository,
    config: dict[str, Any],
    data_iso: str,
    filtros: dict[str, Any],
) -> None:
    st.subheader("Horários disponíveis")
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
        st.info("Nenhum horário disponível para os filtros selecionados.")


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


def _filtrar_agendamentos(agenda: list[dict], data_iso: str, filtros: dict[str, Any]) -> list[dict]:
    return _ordenar_agendamentos(
        item
        for item in agenda
        if item.get("data") == data_iso
        and _passa_status(item, filtros.get("status"))
        and _passa_servico(item, filtros.get("servico"))
        and _passa_profissional(item, filtros.get("profissional"))
    )


def _filtrar_cancelados(agenda: list[dict], data_iso: str, filtros: dict[str, Any]) -> list[dict]:
    return _ordenar_agendamentos(
        item
        for item in agenda
        if item.get("data") == data_iso
        and item.get("status") == "cancelado"
        and _passa_servico(item, filtros.get("servico"))
        and _passa_profissional(item, filtros.get("profissional"))
    )


def _filtrar_remarcados(agenda: list[dict], data_iso: str, filtros: dict[str, Any]) -> list[dict]:
    return _ordenar_agendamentos(
        item
        for item in agenda
        if item.get("data") == data_iso
        and _foi_remarcado(item)
        and _passa_servico(item, filtros.get("servico"))
        and _passa_profissional(item, filtros.get("profissional"))
    )


def _proximos_agendamentos(agenda: list[dict], filtros: dict[str, Any], limite: int = 5) -> list[dict]:
    hoje_iso = date.today().isoformat()
    proximos = _ordenar_agendamentos(
        item
        for item in agenda
        if item.get("status") == "agendado"
        and str(item.get("data", "")) >= hoje_iso
        and _passa_servico(item, filtros.get("servico"))
        and _passa_profissional(item, filtros.get("profissional"))
    )
    return proximos[:limite]


def _passa_status(agendamento: dict, status: str | None) -> bool:
    if status is None:
        return True
    if status == "remarcado":
        return _foi_remarcado(agendamento)
    return agendamento.get("status") == status


def _passa_servico(agendamento: dict, servico: str | None) -> bool:
    return servico is None or agendamento.get("servico") == servico


def _passa_profissional(agendamento: dict, profissional: str | None) -> bool:
    return profissional is None or agendamento.get("profissional") == profissional


def _foi_remarcado(agendamento: dict) -> bool:
    if agendamento.get("remarcado_em"):
        return True
    return any(evento.get("acao") == "remarcado" for evento in agendamento.get("historico", []))


def _formatar_agendamentos_painel(agendamentos: list[dict]) -> list[dict]:
    return [
        {
            "Data": _formatar_data(item.get("data", "")),
            "Horário": item.get("horario", ""),
            "Cliente": item.get("nome", ""),
            "Serviço": _capitalizar(str(item.get("servico", ""))),
            "Profissional": item.get("profissional", ""),
            "Telefone": item.get("telefone", ""),
            "Status": _status_visual(item),
            "Cancelado em": item.get("cancelado_em", ""),
            "Remarcado em": item.get("remarcado_em", ""),
        }
        for item in agendamentos
    ]


def _mostrar_tabela(dados: list[dict] | str) -> None:
    if isinstance(dados, str):
        st.info(dados)
        return
    if not dados:
        st.info("Nenhum registro encontrado para os filtros selecionados.")
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


def _ordenar_agendamentos(agendamentos) -> list[dict]:
    return sorted(
        list(agendamentos),
        key=lambda item: (
            str(item.get("data", "")),
            str(item.get("horario", "")),
            str(item.get("profissional", "")),
        ),
    )


def _opcoes_unicas(*listas) -> list[str]:
    opcoes = []
    for lista in listas:
        for item in lista:
            if item and item not in opcoes:
                opcoes.append(item)
    return sorted(opcoes)


def _proximo_horario(proximos: list[dict]) -> str | None:
    if not proximos:
        return None
    primeiro = proximos[0]
    data_item = _formatar_data(primeiro.get("data", ""))
    horario = primeiro.get("horario", "")
    return f"{data_item} {horario}".strip()


def _status_visual(agendamento: dict) -> str:
    if agendamento.get("status") == "cancelado":
        return "Cancelado"
    if _foi_remarcado(agendamento):
        return "Remarcado"
    if agendamento.get("status") == "agendado":
        return "Agendado"
    return str(agendamento.get("status", "")).capitalize()


def _formatar_data(data_iso: str) -> str:
    return formatters.formatar_data_br(str(data_iso))


def _capitalizar(texto: str) -> str:
    return " ".join(parte.capitalize() for parte in texto.split())


def _cidade_estado(config: dict[str, Any]) -> str:
    cidade = config.get("cidade", "")
    estado = config.get("estado", "")
    if cidade and estado:
        return f"{cidade} - {estado}"
    return cidade or estado


if __name__ == "__main__":
    main()
