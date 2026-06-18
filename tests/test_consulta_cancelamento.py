from datetime import date

from core.conversation.flow import AtendimentoFlow
from core.storage.json_repository import JsonAgendaRepository


def test_consulta_encontra_agendamento_pelo_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos(
        [
            {
                "id": "1",
                "nome": "Marcos Eduardo",
                "telefone": "14999999999",
                "servico": "corte",
                "data": "2026-06-18",
                "horario": "15:00",
                "profissional": "Marcos",
                "duracao_minutos": 30,
                "status": "agendado",
            }
        ]
    )
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    assert "telefone" in flow.receber("consultar")
    resposta = flow.receber("(14) 99999-9999")

    assert "Encontrei estes agendamentos" in resposta
    assert "Corte com Marcos em 18/06/2026 às 15:00" in resposta


def test_consulta_ignora_agendamento_cancelado(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos(
        [
            {
                "id": "1",
                "telefone": "14999999999",
                "servico": "corte",
                "data": "2026-06-18",
                "horario": "15:00",
                "profissional": "Marcos",
                "status": "cancelado",
            }
        ]
    )
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("ver agendamento")
    resposta = flow.receber("14999999999")

    assert "Não encontrei agendamentos ativos" in resposta


def test_cancelamento_altera_status_e_adiciona_cancelado_em(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos(
        [
            {
                "id": "1",
                "nome": "Marcos Eduardo",
                "telefone": "14999999999",
                "servico": "corte",
                "data": "2026-06-18",
                "horario": "15:00",
                "profissional": "Marcos",
                "duracao_minutos": 30,
                "status": "agendado",
            }
        ]
    )
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    assert "telefone" in flow.receber("desmarcar")
    assert "Encontrei estes agendamentos ativos" in flow.receber("14999999999")
    assert "Tem certeza" in flow.receber("1")
    resposta = flow.receber("sim")

    agendamento = repository.listar_agendamentos()[0]
    assert "cancelado" in resposta.lower()
    assert agendamento["status"] == "cancelado"
    assert "cancelado_em" in agendamento
    assert agendamento["historico"][-1]["acao"] == "cancelado"


def test_consulta_informa_quando_agendamento_ja_foi_remarcado(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos(
        [
            {
                "id": "1",
                "nome": "Marcos Eduardo",
                "telefone": "14999999999",
                "servico": "corte",
                "data": "2026-06-19",
                "horario": "14:30",
                "profissional": "Marcos",
                "duracao_minutos": 30,
                "status": "agendado",
                "remarcado_em": "2026-06-18T16:10:00",
            }
        ]
    )
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("meu horário")
    resposta = flow.receber("14999999999")

    assert "Corte com Marcos em 19/06/2026 às 14:30" in resposta
    assert "já foi remarcado" in resposta
