from datetime import date

from core.conversation.flow import AtendimentoFlow
from core.storage.json_repository import JsonAgendaRepository


def test_fluxo_completo_salva_agendamento(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    assert "agendar" in flow.iniciar()
    assert "Qual dia" in flow.receber("agendar")
    assert "Qual serviço" in flow.receber("amanhã")
    assert "preferência" in flow.receber("corte")
    assert "manhã ou tarde" in flow.receber("não")
    assert "09:00" in flow.receber("manhã")
    assert "nome" in flow.receber("10")

    pergunta_telefone = flow.receber("Marcos Eduardo")
    assert "telefone" in pergunta_telefone

    confirmacao = flow.receber("(14) 99999-9999")
    assert "Nome: Marcos Eduardo" in confirmacao
    assert "Telefone: 14999999999" in confirmacao
    assert "Profissional: Marcos" in confirmacao

    resposta_final = flow.receber("sim")
    assert "Agendamento confirmado" in resposta_final

    agenda = repository.listar()
    assert len(agenda) == 1
    assert agenda[0]["nome"] == "Marcos Eduardo"
    assert agenda[0]["telefone"] == "14999999999"
    assert agenda[0]["servico"] == "corte"
    assert agenda[0]["data"] == "2026-06-17"
    assert agenda[0]["horario"] == "10:00"
    assert agenda[0]["profissional"] == "Marcos"
    assert agenda[0]["status"] == "agendado"
    assert "criado_em" in agenda[0]


def test_cancelar_em_qualquer_etapa_nao_salva(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    assert "Qual dia" in flow.receber("agendar")

    resposta = flow.receber("cancelar")

    assert "cancelado" in resposta
    assert flow.encerrado is True
    assert repository.listar() == []


def test_respostas_invalidas_repetem_pergunta(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    assert "Resposta inválida" in flow.receber("talvez")
    flow.receber("agendar")
    assert "Data inválida" in flow.receber("31/02/2026")
    flow.receber("hoje")
    assert "Serviço inválido" in flow.receber("massagem")


def test_telefone_invalido_repetido_antes_da_confirmacao(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("amanhã")
    flow.receber("corte")
    flow.receber("não")
    flow.receber("manhã")
    flow.receber("10")
    flow.receber("Marcos Eduardo")

    resposta = flow.receber("123")

    assert "Telefone inválido" in resposta
    assert flow.state.etapa == "telefone"
