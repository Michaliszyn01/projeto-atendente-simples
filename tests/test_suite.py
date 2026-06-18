from datetime import date
import inspect
from pathlib import Path
import re
import shutil
from uuid import uuid4

import pytest

from app.terminal_app import run_terminal_app
from channels.base import IncomingMessage, OutgoingMessage
from channels.fake_whatsapp import FakeWhatsAppChannel
from channels.terminal import TerminalChannel
from core.config.config_loader import ConfigError, PROJECT_ROOT, carregar_config
import core.conversation.engine as engine_module
from core.conversation.engine import ConversationEngine
from core.conversation.flow import AtendimentoFlow
from core.scheduling.availability import calcular_horarios_disponiveis, tem_conflito
from core.scheduling.validators import normalizar_data, normalizar_telefone, validar_telefone
from core.storage.json_repository import DEFAULT_AGENDA_PATH, JsonAgendaRepository


HOJE = date(2026, 6, 17)


@pytest.fixture
def tmp_path(request):
    base = Path("pytest_tmp")
    base.mkdir(exist_ok=True)
    nome = re.sub(r"[^a-zA-Z0-9_-]+", "_", request.node.name)[:40]
    caminho = base / f"{nome}_{uuid4().hex}"
    caminho.mkdir(parents=True, exist_ok=False)

    try:
        yield caminho
    finally:
        shutil.rmtree(caminho, ignore_errors=True)


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


def test_carregamento_valido_do_config_principal():
    config = carregar_config()

    assert config["modo"] == "barbearia"
    assert config["usa_agendamento"] is True
    assert "corte" in config["servicos"]


def test_config_ausente_gera_erro_claro(tmp_path):
    caminho = tmp_path / "config.json"

    with pytest.raises(ConfigError, match="não encontrado"):
        carregar_config(caminho)


def test_barbearia_carrega_servicos_e_profissionais():
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    assert config["servicos"]["corte"] == 30
    assert config["profissionais"] == ["Marcos", "Julio"]


def test_clinica_usa_medico_como_nome_de_profissional():
    config = carregar_config(PROJECT_ROOT / "exemplos" / "clinica.json")

    assert config["modo"] == "clinica"
    assert config["nome_profissional"] == "médico"
    assert "médico" in config["mensagens"]["pergunta_profissional"]


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


def test_disponibilidade_sem_agenda_mostra_profissionais_para_sem_preferencia():
    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido=None,
        periodo="manhã",
        agenda=[],
    )

    assert {"horario": "09:00", "profissional": "Marcos"} in opcoes
    assert {"horario": "09:00", "profissional": "Julio"} in opcoes
    assert {"horario": "11:30", "profissional": "Marcos"} in opcoes


def test_servico_de_60_minutos_nao_passa_do_fim_do_periodo():
    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte + barba",
        profissional_preferido="Marcos",
        periodo="manhã",
        agenda=[],
    )

    horarios = [opcao["horario"] for opcao in opcoes]
    assert "11:00" in horarios
    assert "11:30" not in horarios


def test_conflito_bloqueia_mesmo_profissional_no_intervalo():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte + barba",
            "data": "2026-06-16",
            "horario": "10:00",
            "profissional": "Marcos",
            "duracao_minutos": 60,
            "status": "agendado",
        }
    ]

    assert tem_conflito("2026-06-16", "10:30", "Marcos", 30, agenda) is True
    assert tem_conflito("2026-06-16", "10:30", "Julio", 30, agenda) is False


def test_horario_ocupado_some_somente_para_profissional_ocupado():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        }
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido=None,
        periodo="tarde",
        agenda=agenda,
    )

    assert {"horario": "15:00", "profissional": "Marcos"} not in opcoes
    assert {"horario": "15:00", "profissional": "Julio"} in opcoes


def test_horario_cancelado_volta_a_ficar_disponivel():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "cancelado",
        }
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        agenda=agenda,
    )

    assert {"horario": "15:00", "profissional": "Marcos"} in opcoes


def test_disponibilidade_ignora_o_proprio_agendamento_quando_informado():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        }
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        agenda=agenda,
        ignorar_agendamento_id="1",
    )

    assert {"horario": "15:00", "profissional": "Marcos"} in opcoes


def test_disponibilidade_nao_ignora_outros_agendamentos():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        },
        {
            "id": "2",
            "nome": "Outro Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:30",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        },
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        agenda=agenda,
        ignorar_agendamento_id="1",
    )

    assert {"horario": "15:00", "profissional": "Marcos"} in opcoes
    assert {"horario": "15:30", "profissional": "Marcos"} not in opcoes


def test_repositorio_padrao_aponta_para_data_da_pasta_do_projeto():
    repository = JsonAgendaRepository()

    assert repository.caminho == DEFAULT_AGENDA_PATH
    assert repository.caminho.name == "agenda.json"
    assert repository.caminho.parent.name == "data"


def test_repositorio_cria_arquivo_automaticamente(tmp_path):
    caminho = tmp_path / "agenda.json"

    repository = JsonAgendaRepository(caminho)

    assert caminho.exists()
    assert repository.listar() == []


def test_repositorio_retorna_lista_vazia_para_arquivo_vazio(tmp_path):
    caminho = tmp_path / "agenda.json"
    caminho.write_text("", encoding="utf-8")

    repository = JsonAgendaRepository(caminho)

    assert repository.listar() == []
    assert caminho.read_text(encoding="utf-8").strip() == "[]"


def test_repositorio_recria_json_corrompido_com_lista_vazia(tmp_path):
    caminho = tmp_path / "agenda.json"
    caminho.write_text("{json quebrado", encoding="utf-8")

    repository = JsonAgendaRepository(caminho)

    assert repository.listar() == []
    assert caminho.read_text(encoding="utf-8").strip() == "[]"


def test_repositorio_busca_agendamentos_ativos_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos(
        [
            {"id": "1", "telefone": "14999999999", "status": "agendado"},
            {"id": "2", "telefone": "(14) 99999-9999", "status": "cancelado"},
            {"id": "3", "telefone": "14888888888", "status": "agendado"},
        ]
    )

    encontrados = repository.buscar_agendamentos_por_telefone("(14) 99999-9999")

    assert [item["id"] for item in encontrados] == ["1"]


def test_repositorio_atualiza_agendamento_por_id(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.adicionar_agendamento({"id": "1", "status": "agendado"})

    atualizado = repository.atualizar_agendamento("1", {"status": "cancelado"})

    assert atualizado["status"] == "cancelado"
    assert repository.listar_agendamentos()[0]["status"] == "cancelado"


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

    assert "loja" in inicio.lower()
    assert "categoria" in resposta.lower()
    assert "informática" in resposta
    assert "Qual dia" not in resposta
    assert "horário" not in resposta


def test_loja_nao_tenta_remarcar_horario(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "loja.json")
    flow = AtendimentoFlow(JsonAgendaRepository(tmp_path / "agenda.json"), config=config)

    flow.iniciar()
    resposta = flow.receber("remarcar")

    assert "não está disponível para loja" in resposta
    assert flow.state.etapa == "escolha_inicial"


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
    flow.receber("14999999999")
    resposta = flow.receber("sim")

    assert "Agendamento confirmado" in resposta
    assert agenda.listar()[0]["servico"] == "corte"
    assert agenda.listar()[0]["telefone"] == "14999999999"


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


def test_telefone_normalizado_remove_mascara():
    assert normalizar_telefone("(14) 99999-9999") == "14999999999"
    assert normalizar_telefone("14 99999 9999") == "14999999999"


def test_telefone_invalido_deve_ser_rejeitado():
    assert validar_telefone("123") is None
    assert validar_telefone("(14) 9999-9999") == "1499999999"


def test_engine_inicia_conversa_e_retorna_menu_inicial(tmp_path):
    engine = ConversationEngine(agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"))

    resposta = engine.start("cliente_1")

    assert "agendar" in resposta
    assert engine.is_finished("cliente_1") is False


def test_engine_mantem_estado_por_session_id(tmp_path):
    engine = ConversationEngine(agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"))

    engine.start("cliente_1")
    engine.start("cliente_2")
    resposta_1 = engine.process_message("cliente_1", "agendar")
    resposta_2 = engine.process_message("cliente_2", "consultar")

    assert "Qual dia" in resposta_1
    assert "telefone" in resposta_2
    assert engine.session_store.get_or_create("cliente_1").etapa == "dia"
    assert engine.session_store.get_or_create("cliente_2").etapa == "consulta_telefone"


def test_engine_duas_sessoes_nao_misturam_dados(tmp_path):
    engine = ConversationEngine(agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"), hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.start("cliente_2")
    engine.process_message("cliente_1", "agendar")
    engine.process_message("cliente_1", "amanhã")
    engine.process_message("cliente_2", "agendar")

    estado_1 = engine.session_store.get_or_create("cliente_1")
    estado_2 = engine.session_store.get_or_create("cliente_2")
    assert estado_1.data == "2026-06-19"
    assert estado_1.etapa == "servico"
    assert estado_2.data is None
    assert estado_2.etapa == "dia"


def test_engine_processa_fluxo_de_agendamento_sem_input_print(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    mensagens = ["agendar", "amanhã", "corte", "não", "manha", "10:00", "Marcos Eduardo", "14999999999", "sim"]
    respostas = [engine.process_message("cliente_1", mensagem) for mensagem in mensagens]

    assert "Agendamento confirmado" in respostas[-1]
    assert repository.listar_agendamentos()[0]["data"] == "2026-06-19"
    assert repository.listar_agendamentos()[0]["telefone"] == "14999999999"


def test_engine_processa_consulta_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos([agendamento_base()])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    assert "telefone" in engine.process_message("cliente_1", "consultar")
    resposta = engine.process_message("cliente_1", "(14) 99999-9999")

    assert "Corte com Marcos em 18/06/2026 às 15:00" in resposta


def test_engine_processa_cancelamento_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos([agendamento_base()])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "cancelar")
    engine.process_message("cliente_1", "14999999999")
    engine.process_message("cliente_1", "1")
    resposta = engine.process_message("cliente_1", "sim")

    assert "cancelado" in resposta.lower()
    assert repository.listar_agendamentos()[0]["status"] == "cancelado"


def test_engine_processa_remarcacao_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar_agendamentos([agendamento_base()])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "remarcar")
    engine.process_message("cliente_1", "14999999999")
    engine.process_message("cliente_1", "1")
    engine.process_message("cliente_1", "19/06/2026")
    engine.process_message("cliente_1", "tarde")
    engine.process_message("cliente_1", "14:30")
    resposta = engine.process_message("cliente_1", "sim")

    agendamento = repository.listar_agendamentos()[0]
    assert "remarcado" in resposta.lower()
    assert agendamento["data"] == "2026-06-19"
    assert agendamento["horario"] == "14:30"


def test_engine_modo_loja_continua_funcionando(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "loja.json")
    solicitacoes = JsonAgendaRepository(tmp_path / "solicitacoes.json")
    engine = ConversationEngine(
        config=config,
        agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"),
        solicitacao_repository=solicitacoes,
    )

    inicio = engine.start("cliente_1")
    resposta_categoria = engine.process_message("cliente_1", "ver produtos")

    assert "loja" in inicio.lower()
    assert "informática" in resposta_categoria


def test_terminal_app_eh_fino_sem_regra_de_negocio_pesada():
    codigo = inspect.getsource(run_terminal_app)

    assert "ConversationEngine" in codigo
    assert "TerminalChannel" in codigo
    assert "AtendimentoFlow" not in codigo
    assert "criar_agendamento" not in codigo
    assert "cancelar_agendamento" not in codigo
    assert "remarcar_agendamento" not in codigo


def test_conversation_engine_nao_usa_input_ou_print():
    codigo = inspect.getsource(engine_module)

    assert "input(" not in codigo
    assert "print(" not in codigo


def test_incoming_message_guarda_canal_remetente_e_texto():
    mensagem = IncomingMessage(channel="terminal", sender_id="cliente_1", text="agendar")

    assert mensagem.channel == "terminal"
    assert mensagem.sender_id == "cliente_1"
    assert mensagem.text == "agendar"
    assert mensagem.raw is None


def test_outgoing_message_guarda_canal_destinatario_e_texto():
    mensagem = OutgoingMessage(channel="terminal", recipient_id="cliente_1", text="Olá")

    assert mensagem.channel == "terminal"
    assert mensagem.recipient_id == "cliente_1"
    assert mensagem.text == "Olá"
    assert mensagem.raw is None


def test_terminal_channel_existe_e_nao_contem_regra_de_agendamento():
    codigo = inspect.getsource(TerminalChannel)
    channel = TerminalChannel()

    assert channel.channel_name == "terminal"
    assert "input(" in codigo
    assert "print(" in codigo
    assert "AtendimentoFlow" not in codigo
    assert "ConversationEngine" not in codigo
    assert "criar_agendamento" not in codigo
    assert "cancelar_agendamento" not in codigo
    assert "remarcar_agendamento" not in codigo


def test_fake_whatsapp_channel_cria_mensagem_de_entrada():
    channel = FakeWhatsAppChannel()

    incoming = channel.build_incoming("14999999999", "agendar")

    assert incoming.channel == "fake_whatsapp"
    assert incoming.sender_id == "14999999999"
    assert incoming.text == "agendar"
    assert incoming.raw == {"phone": "14999999999", "text": "agendar"}


def test_fake_whatsapp_channel_armazena_mensagem_enviada():
    channel = FakeWhatsAppChannel()
    outgoing = OutgoingMessage(
        channel="fake_whatsapp",
        recipient_id="14999999999",
        text="Olá",
    )

    channel.send(outgoing)

    assert channel.sent_messages == [outgoing]


def test_engine_funciona_com_sender_id_do_fake_whatsapp(tmp_path):
    channel = FakeWhatsAppChannel()
    engine = ConversationEngine(agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"))

    incoming = channel.build_incoming("14999999999", "agendar")
    engine.start(incoming.sender_id)
    response_text = engine.process_message(incoming.sender_id, incoming.text)
    channel.send(
        OutgoingMessage(
            channel=incoming.channel,
            recipient_id=incoming.sender_id,
            text=response_text,
        )
    )

    assert "Qual dia" in channel.sent_messages[0].text


def test_fake_whatsapp_duas_sessoes_nao_misturam_estado(tmp_path):
    channel = FakeWhatsAppChannel()
    engine = ConversationEngine(
        agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"),
        hoje=date(2026, 6, 18),
    )

    mensagem_1 = channel.build_incoming("14999999999", "agendar")
    mensagem_2 = channel.build_incoming("14888888888", "consultar")
    engine.start(mensagem_1.sender_id)
    engine.start(mensagem_2.sender_id)
    resposta_1 = engine.process_message(mensagem_1.sender_id, mensagem_1.text)
    resposta_2 = engine.process_message(mensagem_2.sender_id, mensagem_2.text)

    assert "Qual dia" in resposta_1
    assert "telefone" in resposta_2
    assert engine.session_store.get_or_create("14999999999").etapa == "dia"
    assert engine.session_store.get_or_create("14888888888").etapa == "consulta_telefone"


def test_terminal_continua_usando_mesma_engine_via_canal():
    codigo = inspect.getsource(run_terminal_app)

    assert "TerminalChannel" in codigo
    assert "engine.process_message" in codigo
    assert "OutgoingMessage" in codigo
