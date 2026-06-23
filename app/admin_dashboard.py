from datetime import date, timedelta
import html
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
    _aplicar_estilos()

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
            "Agenda",
            "Próximos horários",
            "Cancelamentos",
            "Remarcações",
            "Horários livres",
            "Solicitações",
            "Ajuda",
        ]
    )

    with abas[0]:
        _mostrar_visao_geral(resumo, agendamentos_filtrados, proximos, cancelados, remarcados)

    with abas[1]:
        st.subheader("Agenda do dia")
        _mostrar_tabela(
            _formatar_agendamentos_painel(agendamentos_filtrados),
            "Nenhum agendamento encontrado para este filtro.",
        )

    with abas[2]:
        st.subheader("Próximos horários")
        _mostrar_tabela(
            _formatar_agendamentos_painel(proximos),
            "Nenhum próximo horário encontrado para este filtro.",
        )

    with abas[3]:
        st.subheader("Resumo de cancelamentos")
        _mostrar_tabela(
            _formatar_agendamentos_painel(cancelados),
            "Nenhum cancelamento encontrado para este filtro.",
        )

    with abas[4]:
        st.subheader("Resumo de remarcações")
        _mostrar_tabela(
            _formatar_agendamentos_painel(remarcados),
            "Nenhuma remarcação encontrada para este filtro.",
        )

    with abas[5]:
        _mostrar_horarios_disponiveis(agenda_repository, config, data_iso, filtros)

    with abas[6]:
        st.subheader("Solicitações da loja")
        _mostrar_tabela(
            formatters.formatar_tabela_solicitacoes(solicitacoes),
            "Nenhuma solicitação encontrada.",
        )

    with abas[7]:
        _mostrar_ajuda_demo()


def _mostrar_cabecalho(config: dict[str, Any]) -> None:
    nome_estabelecimento = config.get("nome_estabelecimento", "Estabelecimento")
    detalhes = [
        _cidade_estado(config),
        config.get("endereco", ""),
        config.get("telefone_estabelecimento", ""),
        config.get("instagram", ""),
    ]
    detalhes = [detalhe for detalhe in detalhes if detalhe]
    detalhes_html = " &bull; ".join(_escapar(detalhe) for detalhe in detalhes)

    st.markdown(
        f"""
        <section class="hero-panel">
            <div>
                <div class="eyebrow">Ambiente de demonstração</div>
                <h1>{_escapar(nome_estabelecimento)}</h1>
                <p>Painel operacional para agendamentos, atendimentos e solicitações.</p>
                <div class="hero-meta">{detalhes_html}</div>
            </div>
            <div class="status-pill">
                <span class="status-dot"></span>
                Operação ativa
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _sidebar(config: dict[str, Any], agenda: list[dict]) -> dict[str, Any]:
    st.sidebar.header("Filtros")
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

    modo_demo = st.sidebar.checkbox("Modo demonstração")
    if modo_demo:
        st.sidebar.info("Cenário fictício ativo para apresentação.")

    _mostrar_divisor_sidebar()
    st.sidebar.subheader("Estabelecimento")
    dados = formatters.formatar_dados_estabelecimento(config)
    for campo, valor in dados.items():
        st.sidebar.markdown(f"**{campo}**  \n{valor}")

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
    cards = [
        ("AG", "Agendamentos hoje", resumo.get("total_agendamentos_ativos", 0), "Ativos na data selecionada"),
        ("CA", "Cancelamentos", resumo.get("total_cancelados", 0), "Cancelados no período"),
        ("SV", "Serviços", sum(resumo.get("servicos", {}).values()), "Total de serviços ativos"),
        ("SL", "Solicitações", total_solicitacoes, "Pedidos registrados"),
        ("RM", "Remarcações", len(remarcados), "Ajustes no filtro atual"),
        ("PX", "Próximo horário", _proximo_horario(proximos) or "-", "Agenda futura mais próxima"),
    ]
    colunas = st.columns(len(cards))
    for coluna, (icone, titulo, valor, legenda) in zip(colunas, cards):
        with coluna:
            _metric_card(icone, titulo, valor, legenda)


def _mostrar_visao_geral(
    resumo: dict[str, Any],
    agendamentos: list[dict],
    proximos: list[dict],
    cancelados: list[dict],
    remarcados: list[dict],
) -> None:
    st.subheader("Visão geral da operação")
    _mostrar_resumo_executivo(resumo)

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Serviços mais marcados**")
        _mostrar_tabela(
            _formatar_contagem_tabela(resumo.get("servicos", {})),
            "Nenhum serviço ativo para a data selecionada.",
        )
    with colunas[1]:
        st.markdown("**Quantidade por profissional**")
        _mostrar_tabela(
            _formatar_contagem_tabela(resumo.get("por_profissional", {})),
            "Nenhum profissional com agenda para este filtro.",
        )

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Agenda do dia**")
        _mostrar_tabela(
            _formatar_agendamentos_painel(agendamentos[:5]),
            "Nenhum agendamento encontrado para este filtro.",
        )
    with colunas[1]:
        st.markdown("**Próximos horários**")
        _mostrar_tabela(
            _formatar_agendamentos_painel(proximos[:5]),
            "Nenhum próximo horário encontrado.",
        )

    colunas = st.columns(2)
    with colunas[0]:
        st.markdown("**Cancelamentos**")
        _mostrar_tabela(
            _formatar_agendamentos_painel(cancelados[:5]),
            "Nenhum cancelamento encontrado para este filtro.",
        )
    with colunas[1]:
        st.markdown("**Remarcações**")
        _mostrar_tabela(
            _formatar_agendamentos_painel(remarcados[:5]),
            "Nenhuma remarcação encontrada para este filtro.",
        )


def _mostrar_horarios_disponiveis(
    agenda_repository: JsonAgendaRepository,
    config: dict[str, Any],
    data_iso: str,
    filtros: dict[str, Any],
) -> None:
    st.subheader("Horários livres")
    st.write("Disponibilidade da equipe para o período selecionado.")
    horarios = reports.listar_horarios_disponiveis(
        data=data_iso,
        periodo=filtros["periodo"],
        profissional=filtros["profissional"],
        agenda_repository=agenda_repository,
        config=config,
        servico=filtros["servico"],
    )

    if not horarios:
        _mostrar_empty_state("Nenhum horário livre encontrado para este período.")
        return

    for profissional, lista_horarios in horarios.items():
        st.markdown(f"**{profissional}**")
        if lista_horarios:
            st.markdown(
                '<div class="slot-list">'
                + "".join(f'<span class="slot-pill">{_escapar(horario)}</span>' for horario in lista_horarios)
                + "</div>",
                unsafe_allow_html=True,
            )
        else:
            _mostrar_empty_state("Sem horários livres para este profissional.")


def _mostrar_ajuda_demo() -> None:
    st.subheader("Ajuda da demonstração")
    st.write("Área técnica para preparar dados, abrir o painel e validar a suíte antes da apresentação.")

    st.markdown("**Rodar atendimento no terminal**")
    st.code("python main.py", language="bash")

    st.markdown("**Limpar agenda e solicitações locais**")
    st.code("python scripts/limpar_dados.py", language="bash")

    st.markdown("**Gerar dados fictícios para demonstração**")
    st.code("python scripts/gerar_dados_demo.py", language="bash")

    st.markdown("**Rodar painel administrativo**")
    st.code("streamlit run app/admin_dashboard.py", language="bash")

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
    linhas = []
    for item in agendamentos:
        linha = {
            "Data": _formatar_data(_valor_texto(item.get("data", ""))),
            "Horário": _valor_texto(item.get("horario", "")),
            "Cliente": _valor_texto(item.get("nome", "")),
            "Serviço": _capitalizar(_valor_texto(item.get("servico", ""))),
            "Profissional": _valor_texto(item.get("profissional", "")),
            "Telefone": _formatar_telefone(_valor_texto(item.get("telefone", ""))),
            "Status": _status_visual(item),
            "Cancelado em": _valor_texto(item.get("cancelado_em", "")),
            "Remarcado em": _valor_texto(item.get("remarcado_em", "")),
        }
        linhas.append(linha)
    return linhas


def _mostrar_tabela(
    dados: list[dict] | str,
    mensagem_vazio: str = "Nenhum registro encontrado para os filtros selecionados.",
) -> None:
    if isinstance(dados, str):
        _mostrar_empty_state(dados)
        return
    if not dados:
        _mostrar_empty_state(mensagem_vazio)
        return
    dados = _normalizar_tabela(dados)
    st.dataframe(dados, use_container_width=True)


def _mostrar_empty_state(mensagem: str) -> None:
    st.markdown(
        f'<div class="empty-state">{_escapar(mensagem)}</div>',
        unsafe_allow_html=True,
    )


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
    status = _valor_texto(agendamento.get("status", "")).lower()
    if status == "cancelado":
        return "Cancelado"
    if _foi_remarcado(agendamento):
        return "Remarcado"
    if status == "agendado":
        return "Agendado"
    return _capitalizar(status) if status else ""


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


def _aplicar_estilos() -> None:
    st.markdown(
        """
        <style>
        #MainMenu,
        footer,
        header {
            visibility: hidden;
        }
        .block-container {
            padding-top: 0.9rem;
            padding-bottom: 1.8rem;
        }
        .hero-panel {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            padding: 1.15rem 1.25rem;
            margin-bottom: 0.75rem;
            border: 1px solid #dfe6ee;
            border-radius: 8px;
            background: linear-gradient(135deg, #ffffff 0%, #f7f9fc 56%, #eef5f4 100%);
            box-shadow: 0 12px 30px rgba(22, 35, 49, 0.08);
        }
        .hero-panel h1 {
            margin: 0.1rem 0 0.35rem 0;
            color: #162331;
            font-size: 2rem;
            line-height: 1.15;
            letter-spacing: 0;
        }
        .hero-panel p {
            margin: 0 0 0.45rem 0;
            color: #526173;
            font-size: 1rem;
        }
        .eyebrow {
            color: #1f6f63;
            font-size: 0.76rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0;
        }
        .hero-meta {
            color: #6a7787;
            font-size: 0.88rem;
            line-height: 1.45;
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            white-space: nowrap;
            color: #14564e;
            background: #e8f5f1;
            border: 1px solid #c7e2da;
            border-radius: 999px;
            padding: 0.48rem 0.72rem;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .status-dot {
            width: 0.55rem;
            height: 0.55rem;
            border-radius: 999px;
            background: #1f9d75;
            display: inline-block;
        }
        .metric-card {
            min-height: 118px;
            padding: 0.82rem;
            border: 1px solid #e1e7ef;
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 8px 22px rgba(22, 35, 49, 0.06);
        }
        .metric-top {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            margin-bottom: 0.55rem;
        }
        .metric-icon {
            width: 2rem;
            height: 2rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            color: #174f48;
            background: #eef7f4;
            font-size: 0.72rem;
            font-weight: 800;
        }
        .metric-title {
            color: #526173;
            font-size: 0.78rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .metric-value {
            color: #162331;
            font-size: 1.55rem;
            font-weight: 800;
            line-height: 1.15;
            overflow-wrap: anywhere;
        }
        .metric-caption {
            margin-top: 0.35rem;
            color: #7a8795;
            font-size: 0.76rem;
            line-height: 1.3;
        }
        .summary-strip {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.8rem;
            margin: 0.1rem 0 0.8rem 0;
        }
        .summary-item {
            border: 1px solid #e1e7ef;
            border-radius: 8px;
            padding: 0.85rem;
            background: #fbfcfe;
        }
        .summary-label {
            color: #6a7787;
            font-size: 0.78rem;
            font-weight: 700;
        }
        .summary-value {
            color: #162331;
            font-size: 1.05rem;
            font-weight: 800;
            margin-top: 0.18rem;
        }
        .empty-state {
            border: 1px dashed #cfd8e3;
            border-radius: 8px;
            padding: 1rem;
            color: #657386;
            background: #fbfcfe;
        }
        .slot-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin: 0.35rem 0 0.9rem 0;
        }
        .slot-pill {
            display: inline-flex;
            border: 1px solid #d6e2de;
            border-radius: 999px;
            padding: 0.32rem 0.58rem;
            color: #174f48;
            background: #f2faf7;
            font-weight: 700;
            font-size: 0.85rem;
        }
        [data-testid="stSidebar"] {
            background: #f6f8fb;
            border-right: 1px solid #e1e7ef;
        }
        [data-testid="stSidebar"] * {
            color: #1d2b3a;
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown,
        [data-testid="stSidebar"] p {
            color: #233244;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] > div,
        [data-testid="stSidebar"] input {
            background: #ffffff;
            color: #162331;
            border-color: #ccd6e2;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] span {
            color: #162331;
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
            color: #526173;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0;
        }
        [data-testid="stDataFrame"] {
            border: 1px solid #e4eaf1;
            border-radius: 8px;
            overflow: hidden;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.65rem;
        }
        div[data-testid="stTabs"] button {
            color: #344457;
            font-weight: 700;
        }
        @media (max-width: 900px) {
            .hero-panel {
                flex-direction: column;
            }
            .status-pill {
                white-space: normal;
            }
            .summary-strip {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(icone: str, titulo: str, valor: Any, legenda: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-top">
                <span class="metric-icon">{_escapar(icone)}</span>
                <span class="metric-title">{_escapar(titulo)}</span>
            </div>
            <div class="metric-value">{_escapar(str(valor))}</div>
            <div class="metric-caption">{_escapar(legenda)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _mostrar_resumo_executivo(resumo: dict[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="summary-strip">
            <div class="summary-item">
                <div class="summary-label">Primeiro horário</div>
                <div class="summary-value">{_escapar(resumo.get("primeiro_horario") or "-")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Último horário</div>
                <div class="summary-value">{_escapar(resumo.get("ultimo_horario") or "-")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Profissional em destaque</div>
                <div class="summary-value">{_escapar(resumo.get("profissional_mais_atendimentos") or "-")}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _formatar_telefone(telefone: str) -> str:
    digitos = "".join(caractere for caractere in telefone if caractere.isdigit())
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return telefone


def _normalizar_tabela(linhas: list[dict]) -> list[dict]:
    colunas = []
    for linha in linhas:
        for coluna in linha:
            if coluna not in colunas:
                colunas.append(coluna)

    colunas_visiveis = [
        coluna
        for coluna in colunas
        if any(_valor_tabela(linha.get(coluna)) != "" for linha in linhas)
    ]

    return [
        {
            coluna: (_valor_tabela(linha.get(coluna)) or "-")
            for coluna in colunas_visiveis
        }
        for linha in linhas
    ]


def _valor_tabela(valor: Any) -> Any:
    if valor is None:
        return ""
    if isinstance(valor, str):
        texto = valor.strip()
        if texto.lower() in {"", "none", "nan", "null"}:
            return ""
        return texto
    return valor


def _valor_texto(valor: Any) -> str:
    valor_limpo = _valor_tabela(valor)
    if valor_limpo == "":
        return ""
    return str(valor_limpo)


def _remover_campos_vazios(linha: dict[str, Any]) -> dict[str, Any]:
    return {campo: valor for campo, valor in linha.items() if _valor_tabela(valor) != ""}


def _escapar(valor: Any) -> str:
    return html.escape(str(valor))


if __name__ == "__main__":
    main()
