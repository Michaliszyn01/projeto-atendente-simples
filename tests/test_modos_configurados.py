from datetime import date

from core.config.config_loader import PROJECT_ROOT, carregar_config
from core.conversation.flow import AtendimentoFlow
from core.storage.json_repository import JsonAgendaRepository


def test_clinica_troca_texto_de_profissional_para_medico(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "clinica.json")
    flow = AtendimentoFlow(JsonAgendaRepository(tmp_path / "agenda.json"), hoje=date(2026, 6, 17), config=config)

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("hoje")
    resposta = flow.receber("retorno")

    assert "médico" in resposta
    assert "Dra. Ana" in resposta


def test_loja_sem_agendamento_nao_pede_data_nem_horario(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "loja.json")
    flow = AtendimentoFlow(JsonAgendaRepository(tmp_path / "agenda.json"), config=config)

    inicio = flow.iniciar()
    resposta = flow.receber("ver produtos")

    assert "loja" in inicio
    assert "categoria" in resposta.lower()
    assert "informática" in resposta
    assert "Qual dia" not in resposta
    assert "horário" not in resposta


def test_loja_salva_solicitacao_de_orcamento(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "loja.json")
    solicitacoes = JsonAgendaRepository(tmp_path / "solicitacoes.json")
    flow = AtendimentoFlow(
        JsonAgendaRepository(tmp_path / "agenda.json"),
        config=config,
        solicitacoes_repository=solicitacoes,
    )

    flow.iniciar()
    assert "precisa" in flow.receber("fazer orçamento")
    assert "nome" in flow.receber("notebook para trabalho")
    resposta = flow.receber("Marcos")

    assert "Solicitação registrada" in resposta
    assert solicitacoes.listar()[0]["descricao"] == "notebook para trabalho"


def test_agendamento_continua_funcionando_no_modo_barbearia(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")
    agenda = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(agenda, hoje=date(2026, 6, 17), config=config)

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("amanhã")
    flow.receber("corte")
    flow.receber("não")
    flow.receber("manha")
    flow.receber("10:00")
    flow.receber("Marcos Eduardo")
    resposta = flow.receber("sim")

    assert "Agendamento confirmado" in resposta
    assert agenda.listar()[0]["servico"] == "corte"
