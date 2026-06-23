from core.scheduling.validators import formatar_data_br


MENSAGEM_SEM_AGENDAMENTOS = "Nenhum agendamento encontrado."
MENSAGEM_SEM_SOLICITACOES = "Nenhuma solicitação encontrada."
MENSAGEM_SEM_HORARIOS = "Nenhum horário disponível."


def formatar_agendamento(agendamento: dict) -> dict[str, str]:
    return {
        "data": agendamento.get("data", ""),
        "horário": agendamento.get("horario", ""),
        "serviço": agendamento.get("servico", ""),
        "profissional": agendamento.get("profissional", ""),
        "cliente": agendamento.get("nome", ""),
        "telefone": agendamento.get("telefone", ""),
        "status": agendamento.get("status", ""),
    }


def formatar_agendamento_tabela(agendamento: dict) -> dict[str, str]:
    return {
        "Data": formatar_data_br(str(agendamento.get("data", ""))),
        "Horário": agendamento.get("horario", ""),
        "Serviço": _capitalizar(str(agendamento.get("servico", ""))),
        "Profissional": agendamento.get("profissional", ""),
        "Cliente": agendamento.get("nome", ""),
        "Telefone": agendamento.get("telefone", ""),
        "Status": agendamento.get("status", ""),
    }


def formatar_cancelado(agendamento: dict) -> dict[str, str]:
    dados = formatar_agendamento(agendamento)
    dados.pop("status", None)
    dados["cancelado_em"] = agendamento.get("cancelado_em", "")
    return dados


def formatar_cancelado_tabela(agendamento: dict) -> dict[str, str]:
    dados = formatar_agendamento_tabela(agendamento)
    dados.pop("Status", None)
    dados["Cancelado em"] = agendamento.get("cancelado_em", "")
    return dados


def formatar_lista_agendamentos(agendamentos: list[dict]) -> list[dict[str, str]] | str:
    if not agendamentos:
        return MENSAGEM_SEM_AGENDAMENTOS
    return [formatar_agendamento(agendamento) for agendamento in agendamentos]


def formatar_tabela_agendamentos(agendamentos: list[dict]) -> list[dict[str, str]] | str:
    if not agendamentos:
        return MENSAGEM_SEM_AGENDAMENTOS
    return [formatar_agendamento_tabela(agendamento) for agendamento in agendamentos]


def formatar_lista_cancelados(agendamentos: list[dict]) -> list[dict[str, str]] | str:
    if not agendamentos:
        return MENSAGEM_SEM_AGENDAMENTOS
    return [formatar_cancelado(agendamento) for agendamento in agendamentos]


def formatar_tabela_cancelados(agendamentos: list[dict]) -> list[dict[str, str]] | str:
    if not agendamentos:
        return MENSAGEM_SEM_AGENDAMENTOS
    return [formatar_cancelado_tabela(agendamento) for agendamento in agendamentos]


def formatar_solicitacoes(solicitacoes: list[dict]) -> list[dict[str, str]] | str:
    if not solicitacoes:
        return MENSAGEM_SEM_SOLICITACOES
    return [
        {
            "nome": solicitacao.get("nome", ""),
            "telefone": solicitacao.get("telefone", ""),
            "categoria": solicitacao.get("categoria", ""),
            "descrição/pedido": solicitacao.get("descricao") or solicitacao.get("pedido", ""),
            "criado_em": solicitacao.get("criado_em", ""),
            "status": solicitacao.get("status", ""),
        }
        for solicitacao in solicitacoes
    ]


def formatar_tabela_solicitacoes(solicitacoes: list[dict]) -> list[dict[str, str]] | str:
    if not solicitacoes:
        return MENSAGEM_SEM_SOLICITACOES
    return [
        {
            "Nome": solicitacao.get("nome", ""),
            "Telefone": solicitacao.get("telefone", ""),
            "Categoria": solicitacao.get("categoria", ""),
            "Descrição/Pedido": solicitacao.get("descricao") or solicitacao.get("pedido", ""),
            "Criado em": solicitacao.get("criado_em", ""),
            "Status": solicitacao.get("status", ""),
        }
        for solicitacao in solicitacoes
    ]


def formatar_horarios_disponiveis(horarios_por_profissional: dict[str, list[str]]) -> list[dict[str, str]] | str:
    linhas = [
        {"profissional": profissional, "horário": horario}
        for profissional, horarios in horarios_por_profissional.items()
        for horario in horarios
    ]
    return linhas or MENSAGEM_SEM_HORARIOS


def formatar_tabela_horarios_disponiveis(horarios_por_profissional: dict[str, list[str]]) -> list[dict[str, str]] | str:
    linhas = [
        {"Profissional": profissional, "Horário": horario}
        for profissional, horarios in horarios_por_profissional.items()
        for horario in horarios
    ]
    return linhas or MENSAGEM_SEM_HORARIOS


def formatar_contagem_tabela(
    contagem: dict | None,
    nome_coluna: str = "Item",
    valor_coluna: str = "Quantidade",
) -> list[dict]:
    if not contagem:
        return []

    return [
        {
            nome_coluna: item,
            valor_coluna: quantidade,
        }
        for item, quantidade in sorted(
            contagem.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def formatar_resumo_do_dia(resumo: dict) -> str:
    linhas = [
        f"Resumo de {formatar_data_br(str(resumo.get('data', '')))}:",
        f"Total de agendamentos ativos: {resumo.get('total_agendamentos_ativos', 0)}",
        f"Cancelados: {resumo.get('total_cancelados', 0)}",
        "",
        "Serviços:",
    ]
    linhas.extend(_formatar_contagem(resumo.get("servicos", {})))
    linhas.extend(["", "Por profissional:"])
    linhas.extend(_formatar_contagem(resumo.get("por_profissional", {})))
    linhas.extend(
        [
            "",
            f"Primeiro horário: {resumo.get('primeiro_horario') or '-'}",
            f"Último horário: {resumo.get('ultimo_horario') or '-'}",
        ]
    )
    return "\n".join(linhas)


def formatar_dados_estabelecimento(config: dict) -> dict[str, str]:
    campos = {
        "Nome": config.get("nome_estabelecimento", ""),
        "Endereço": config.get("endereco", ""),
        "Telefone": config.get("telefone_estabelecimento", ""),
        "Instagram": config.get("instagram", ""),
        "Cidade": config.get("cidade", ""),
        "Estado": config.get("estado", ""),
    }
    return {campo: valor for campo, valor in campos.items() if valor}


def _formatar_contagem(contagem: dict) -> list[str]:
    if not contagem:
        return ["- Nenhum registro"]
    return [f"- {nome}: {quantidade}" for nome, quantidade in contagem.items()]


def _capitalizar(texto: str) -> str:
    return " ".join(parte.capitalize() for parte in texto.split())
