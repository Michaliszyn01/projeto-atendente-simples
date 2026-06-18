from datetime import date

from core.conversation.flow import AtendimentoFlow
from core.scheduling.validators import normalizar_data
from core.storage.json_repository import JsonAgendaRepository


HOJE = date(2026, 6, 17)


def test_data_no_passado_deve_ser_rejeitada(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=HOJE)

    flow.iniciar()
    flow.receber("agendar")

    resposta = flow.receber("16/06/2026")

    assert "anterior ao dia atual" in resposta
    assert flow.state.data is None


def test_data_de_hoje_deve_ser_aceita():
    assert normalizar_data("hoje", hoje=HOJE) == "2026-06-17"
    assert normalizar_data("17/06/2026", hoje=HOJE) == "2026-06-17"


def test_data_de_amanha_deve_ser_aceita():
    assert normalizar_data("amanhã", hoje=HOJE) == "2026-06-18"
    assert normalizar_data("18/06/2026", hoje=HOJE) == "2026-06-18"


def test_data_invalida_deve_ser_rejeitada():
    assert normalizar_data("31/02/2026", hoje=HOJE) is None
    assert normalizar_data("2026-06-17", hoje=HOJE) is None
