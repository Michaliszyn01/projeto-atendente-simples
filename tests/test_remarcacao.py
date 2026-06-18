from datetime import date

from core.conversation.flow import AtendimentoFlow
from core.storage.json_repository import JsonAgendaRepository


def agendamento_base(**extras):
    agendamento = {
        "id": "agenda-1",
        "nome": "Marcos Eduardo",
        "telefone": "14999999999",
        "servico": "corte",
        "data": "2026-06-18",
        "horario": "15:00",
        "profissional": "Marcos",
        "duracao_minutos": 30,
        "status": "agendado",
        "criado_em": "2026-06-18T14:30:00",
    }
    agendamento.update(extras)
    return agendamento


def test_remarcacao_altera_data_horario_mantem_id_e_nao_duplica(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    assert "telefone" in flow.receber("remarcar")
    assert "Encontrei estes agendamentos ativos" in flow.receber("(14) 99999-9999")
    assert "Para qual dia" in flow.receber("1")
    assert "manhã ou tarde" in flow.receber("19/06/2026")
    assert "14:30" in flow.receber("tarde")
    confirmacao = flow.receber("14:30")
    assert "Confirmando remarcação" in confirmacao
    assert "Corte com Marcos em 18/06/2026 às 15:00" in confirmacao
    assert "Corte com Marcos em 19/06/2026 às 14:30" in confirmacao
    resposta = flow.receber("sim")

    agenda = repository.listar_agendamentos()
    assert "remarcado" in resposta.lower()
    assert len(agenda) == 1
    assert agenda[0]["id"] == "agenda-1"
    assert agenda[0]["data"] == "2026-06-19"
    assert agenda[0]["horario"] == "14:30"


def test_remarcacao_adiciona_remarcado_em_e_historico(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("trocar horário")
    flow.receber("14999999999")
    flow.receber("1")
    flow.receber("19/06/2026")
    flow.receber("tarde")
    flow.receber("14:30")
    flow.receber("sim")

    agendamento = repository.listar_agendamentos()[0]
    evento = agendamento["historico"][-1]
    assert "remarcado_em" in agendamento
    assert evento["acao"] == "remarcado"
    assert evento["data_anterior"] == "2026-06-18"
    assert evento["horario_anterior"] == "15:00"
    assert evento["data_nova"] == "2026-06-19"
    assert evento["horario_novo"] == "14:30"
    assert "feito_em" in evento


def test_remarcacao_respeita_conflito_com_outro_agendamento(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos(
        [
            agendamento_base(),
            agendamento_base(
                id="agenda-2",
                nome="Outro Cliente",
                telefone="14888888888",
                data="2026-06-19",
                horario="14:30",
            ),
        ]
    )
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("mudar agendamento")
    flow.receber("14999999999")
    flow.receber("1")
    flow.receber("19/06/2026")
    resposta = flow.receber("tarde")

    assert "- 14:30" not in resposta
    assert "- 15:00" in resposta


def test_remarcacao_sem_horarios_permite_tentar_outro_dia_ou_periodo(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    ocupados = [
        agendamento_base(id=f"agenda-{indice}", horario=horario, telefone=f"1499999999{indice}")
        for indice, horario in enumerate(
            ["14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30"],
            start=2,
        )
    ]
    repository.salvar_agendamentos([agendamento_base()] + ocupados)
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("remarcar")
    flow.receber("14999999999")
    flow.receber("1")
    flow.receber("18/06/2026")
    resposta = flow.receber("tarde")

    assert "Não encontrei horários disponíveis" in resposta
    assert flow.state.etapa == "remarcacao_sem_disponibilidade"
    assert "Horários disponíveis" in flow.receber("manha")


def test_remarcacao_nao_altera_agendamento_quando_cliente_responde_nao(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("remarcar")
    flow.receber("14999999999")
    flow.receber("1")
    flow.receber("19/06/2026")
    flow.receber("tarde")
    flow.receber("14:30")
    resposta = flow.receber("não")

    agendamento = repository.listar_agendamentos()[0]
    assert "sem alterações" in resposta
    assert agendamento["data"] == "2026-06-18"
    assert agendamento["horario"] == "15:00"
    assert "remarcado_em" not in agendamento
