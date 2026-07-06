from datetime import date
from concurrent.futures import ThreadPoolExecutor
import inspect
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.webhook_api as webhook_api_module
from app.terminal_app import run_terminal_app
from app.webhook_api import app as webhook_app
from channels.base import IncomingMessage, OutgoingMessage
from channels.fake_whatsapp import FakeWhatsAppChannel
from channels.terminal import TerminalChannel
from core.admin import formatters, reports
from core.config.config_loader import ConfigError, PROJECT_ROOT, carregar_config
import core.conversation.engine as engine_module
from core.conversation.engine import ConversationEngine
from core.conversation.flow import AtendimentoFlow
from core.conversation.state import ConversationState
from core.scheduling.availability import calcular_horarios_disponiveis, tem_conflito
from core.scheduling.validators import (
    normalizar_telefone,
    normalizar_telefone_whatsapp,
    validar_data_agendamento,
    validar_telefone,
)
from core.storage.json_repository import DEFAULT_AGENDA_PATH, JsonAgendaRepository
from core.storage.migrate_json_to_sqlite import migrar_json_para_sqlite
from core.storage.repository_factory import criar_agenda_repository
from core.storage.sqlite_repository import SQLiteAgendaRepository, SQLiteSessionStore
from scripts.gerar_dados_demo import CLIENTES_FICTICIOS, criar_agenda_demo, gerar_dados_demo
from scripts.limpar_dados import limpar_dados


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


def webhook_client(
    tmp_path,
    hoje: date | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[TestClient, SQLiteAgendaRepository]:
    if monkeypatch is not None:
        for env_var in (
            "WEBHOOK_API_KEY",
            "META_WHATSAPP_TOKEN",
            "META_WHATSAPP_PHONE_NUMBER_ID",
            "META_WHATSAPP_VERIFY_TOKEN",
            "META_GRAPH_VERSION",
        ):
            monkeypatch.delenv(env_var, raising=False)
    try:
        delattr(webhook_app.state, "meta_client")
    except (AttributeError, KeyError):
        pass
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")
    config["storage"] = {"type": "sqlite", "path": str(tmp_path / "agenda.db")}
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    webhook_app.state.engine = ConversationEngine(
        config=config,
        agenda_repository=repository,
        hoje=hoje,
    )
    return TestClient(webhook_app), repository


def webhook_auth_headers(monkeypatch: pytest.MonkeyPatch, api_key: str = "segredo") -> dict[str, str]:
    monkeypatch.setenv("WEBHOOK_API_KEY", api_key)
    return {"X-API-Key": api_key}


class FakeMetaWhatsAppClient:
    def __init__(self) -> None:
        self.calls = []

    def send_text_message(self, to: str, text: str) -> dict:
        self.calls.append({"to": to, "text": text})
        return {"ok": True, "provider": "fake"}


def meta_text_payload(
    text: str = "agendar",
    phone: str = "5514999999999",
    message_id: str = "wamid.fake-1",
) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5514000000000",
                                "phone_number_id": "123456",
                            },
                            "contacts": [{"profile": {"name": "Eduardo"}, "wa_id": phone}],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "timestamp": "1719250000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def meta_status_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {
                                    "id": "wamid.sent-1",
                                    "status": "delivered",
                                    "recipient_id": "5514999999999",
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }


def assert_humano_solicitado(flow, resposta: str, etapa_origem: str):
    assert "chamar" in resposta.lower() or "encaminhar" in resposta.lower()
    assert "inválid" not in resposta.lower()
    assert flow.encerrado is True
    assert flow.state.etapa == "encerrado"
    assert flow.state.humano_solicitado is True
    assert flow.state.etapa_antes_humano == etapa_origem


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


def test_data_invalida_mostra_opcoes_de_recuperacao(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    resposta = flow.receber("31/02/2026")

    assert "Data inválida" in resposta
    assert "cancelar" in resposta
    assert "recomeçar" in resposta
    assert "humano" not in resposta


def test_servico_invalido_mostra_opcoes_de_recuperacao(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("amanhã")
    resposta = flow.receber("massagem")

    assert "Serviço inválido" in resposta
    assert "cancelar" in resposta
    assert "recomeçar" in resposta


def test_horario_invalido_mostra_opcoes_de_recuperacao(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("amanhã")
    flow.receber("corte")
    flow.receber("não")
    flow.receber("manhã")
    resposta = flow.receber("cedo")

    assert "Horário inválido" in resposta
    assert "cancelar" in resposta
    assert "recomeçar" in resposta


def test_humano_aparece_como_sugestao_apos_tres_erros_invalidos(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    primeira = flow.receber("31/02/2026")
    flow.receber("32/02/2026")
    terceira = flow.receber("33/02/2026")

    assert "humano" not in primeira
    assert "humano" in terceira
    assert flow.state.erros_invalidos_consecutivos == 3


def test_resposta_valida_zera_contador_de_erros_invalidos(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("31/02/2026")
    assert flow.state.erros_invalidos_consecutivos == 1

    resposta = flow.receber("amanhã")

    assert "Qual serviço" in resposta
    assert flow.state.erros_invalidos_consecutivos == 0


def test_recomecar_volta_ao_inicio_sem_apagar_agendamentos(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    resposta = flow.receber("recomeçar")

    assert "agendar" in resposta
    assert flow.state.etapa == "escolha_inicial"
    assert flow.state.erros_invalidos_consecutivos == 0
    assert repository.listar()[0]["id"] == "agenda-1"


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


def test_humano_funciona_no_menu_inicial_e_registra_na_sessao(tmp_path):
    engine = ConversationEngine(agenda_repository=JsonAgendaRepository(tmp_path / "agenda.json"))

    engine.start("cliente_1")
    resposta = engine.process_message("cliente_1", "humano")
    state = engine.session_store.get_or_create("cliente_1")

    assert "chamar" in resposta.lower() or "encaminhar" in resposta.lower()
    assert engine.is_finished("cliente_1") is True
    assert state.humano_solicitado is True
    assert state.etapa_antes_humano == "escolha_inicial"


def test_humano_funciona_na_etapa_de_escolher_data(tmp_path):
    flow = AtendimentoFlow(JsonAgendaRepository(tmp_path / "agenda.json"), hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    resposta = flow.receber("quero falar com alguém")

    assert_humano_solicitado(flow, resposta, "dia")


def test_humano_funciona_na_etapa_de_escolher_horario(tmp_path):
    flow = AtendimentoFlow(JsonAgendaRepository(tmp_path / "agenda.json"), hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("amanhã")
    flow.receber("corte")
    flow.receber("não")
    flow.receber("manhã")
    resposta = flow.receber("suporte")

    assert_humano_solicitado(flow, resposta, "horario")


def test_humano_funciona_na_etapa_de_informar_nome(tmp_path):
    flow = AtendimentoFlow(JsonAgendaRepository(tmp_path / "agenda.json"), hoje=date(2026, 6, 16))

    flow.iniciar()
    flow.receber("agendar")
    flow.receber("amanhã")
    flow.receber("corte")
    flow.receber("não")
    flow.receber("manhã")
    flow.receber("10")
    resposta = flow.receber("pessoa")

    assert_humano_solicitado(flow, resposta, "nome")


def test_humano_funciona_na_etapa_de_cancelamento(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("cancelar")
    flow.receber("14999999999")
    resposta = flow.receber("me chama alguém")

    assert_humano_solicitado(flow, resposta, "cancelamento_escolha")
    assert repository.listar()[0]["status"] == "agendado"


def test_humano_funciona_na_etapa_de_remarcacao(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("remarcar")
    flow.receber("14999999999")
    flow.receber("1")
    resposta = flow.receber("atendente")

    assert_humano_solicitado(flow, resposta, "remarcacao_dia")
    assert repository.listar()[0]["data"] == "2026-06-18"


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
    repository.salvar(
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
    repository.salvar(
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
    repository.salvar(
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

    agendamento = repository.listar()[0]
    assert "cancelado" in resposta.lower()
    assert agendamento["status"] == "cancelado"
    assert "cancelado_em" in agendamento
    assert agendamento["historico"][-1]["acao"] == "cancelado"


def test_consulta_informa_quando_agendamento_ja_foi_remarcado(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
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
    repository.salvar(
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
    assert repository.listar()[0]["status"] == "cancelado"


def test_factory_padrao_usa_sqlite_com_config(tmp_path):
    repository = criar_agenda_repository(
        {"storage": {"type": "sqlite", "path": str(tmp_path / "agenda.db")}}
    )

    assert isinstance(repository, SQLiteAgendaRepository)
    assert repository.caminho == (tmp_path / "agenda.db").resolve()


def test_sqlite_repository_salva_agendamento_e_vincula_telefone(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.adicionar_agendamento(agendamento_base(telefone="+55 (14) 99999-9999"))

    agenda = repository.listar()
    encontrados = repository.buscar_agendamentos_por_telefone("whatsapp:+5514999999999")

    assert agenda[0]["telefone_normalizado"] == "5514999999999"
    assert agenda[0]["cliente_id"] == "5514999999999"
    assert [item["id"] for item in encontrados] == ["agenda-1"]


def test_sqlite_cancelamento_persiste_historico_no_payload_json(tmp_path):
    db_path = tmp_path / "agenda.db"
    repository = SQLiteAgendaRepository(db_path)
    repository.adicionar_agendamento(
        agendamento_base(historico=[{"acao": "criado", "feito_em": "2026-06-18T14:00:00"}])
    )

    repository.cancelar_agendamento("agenda-1")
    reaberto = SQLiteAgendaRepository(db_path)
    agendamento = reaberto.buscar_agendamento_por_id("agenda-1")

    assert agendamento["status"] == "cancelado"
    assert [evento["acao"] for evento in agendamento["historico"]] == ["criado", "cancelado"]


def test_sqlite_remarcacao_persiste_historico_sem_perder_eventos(tmp_path):
    db_path = tmp_path / "agenda.db"
    repository = SQLiteAgendaRepository(db_path)
    repository.adicionar_agendamento(
        agendamento_base(historico=[{"acao": "criado", "feito_em": "2026-06-18T14:00:00"}])
    )

    repository.remarcar_agendamento("agenda-1", "2026-06-19", "14:30", "Marcos")
    reaberto = SQLiteAgendaRepository(db_path)
    agendamento = reaberto.buscar_agendamento_por_id("agenda-1")

    assert agendamento["data"] == "2026-06-19"
    assert agendamento["horario"] == "14:30"
    assert [evento["acao"] for evento in agendamento["historico"]] == ["criado", "remarcado"]
    assert agendamento["historico"][-1]["data_anterior"] == "2026-06-18"


def test_sqlite_repository_nao_permite_dois_ativos_no_mesmo_horario(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.adicionar_agendamento(agendamento_base(id="agenda-1"))

    with pytest.raises(ValueError):
        repository.adicionar_agendamento(
            agendamento_base(id="agenda-2", nome="Outro Cliente", telefone="14888888888")
        )

    assert [item["id"] for item in repository.listar()] == ["agenda-1"]


def test_sqlite_repository_cancelado_libera_horario(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.adicionar_agendamento(agendamento_base(id="cancelado", status="cancelado"))
    repository.adicionar_agendamento(
        agendamento_base(id="novo", nome="Novo Cliente", telefone="14888888888")
    )

    assert [item["id"] for item in repository.listar()] == ["cancelado", "novo"]


def test_sqlite_repository_uso_concorrente_basico_nao_quebra(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")

    def adicionar(indice: int) -> None:
        repository.adicionar_agendamento(
            agendamento_base(
                id=f"agenda-{indice}",
                telefone=f"1499999999{indice}",
                horario=f"1{indice}:00",
            )
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(adicionar, range(4)))

    assert len(repository.listar()) == 4


def test_sqlite_session_store_separa_sessoes_e_persiste(tmp_path):
    db_path = tmp_path / "agenda.db"
    store = SQLiteSessionStore(db_path)
    store.save("+55 (14) 99999-9999", ConversationState(etapa="dia", nome="Ana"))
    store.save("+55 (14) 88888-8888", ConversationState(etapa="consulta_telefone", nome="Bia"))

    reaberto = SQLiteSessionStore(db_path)

    assert reaberto.get_or_create("whatsapp:+5514999999999").etapa == "dia"
    assert reaberto.get_or_create("5514888888888").etapa == "consulta_telefone"


def test_sqlite_cancelamento_e_remarcacao_buscam_por_telefone(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.salvar([agendamento_base(telefone="+55 (14) 99999-9999")])

    cancelamento = AtendimentoFlow(repository, hoje=date(2026, 6, 18))
    cancelamento.iniciar()
    cancelamento.receber("cancelar")
    assert "ativos" in cancelamento.receber("whatsapp:+5514999999999")
    cancelamento.receber("1")
    resposta_cancelamento = cancelamento.receber("sim")

    assert "cancelado" in resposta_cancelamento.lower()
    assert repository.buscar_agendamento_por_id("agenda-1")["status"] == "cancelado"

    repository.salvar([agendamento_base(id="agenda-2", telefone="+55 (14) 99999-9999")])
    remarcacao = AtendimentoFlow(repository, hoje=date(2026, 6, 18))
    remarcacao.iniciar()
    remarcacao.receber("remarcar")
    assert "ativos" in remarcacao.receber("14999999999")
    remarcacao.receber("1")
    remarcacao.receber("19/06/2026")
    remarcacao.receber("tarde")
    remarcacao.receber("14:30")
    resposta_remarcacao = remarcacao.receber("sim")

    atualizado = repository.buscar_agendamento_por_id("agenda-2")
    assert "remarcado" in resposta_remarcacao.lower()
    assert atualizado["data"] == "2026-06-19"
    assert atualizado["horario"] == "14:30"
    assert atualizado["telefone_normalizado"] == "5514999999999"


def test_migracao_json_para_sqlite_nao_duplica_dados(tmp_path):
    json_path = tmp_path / "agenda.json"
    db_path = tmp_path / "agenda.db"
    json_path.write_text(
        json.dumps(
            [
                agendamento_base(id="json-1"),
                agendamento_base(id="json-2", horario="16:00"),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    primeiro_resumo = migrar_json_para_sqlite(json_path, db_path)
    segundo_resumo = migrar_json_para_sqlite(json_path, db_path)
    repository = SQLiteAgendaRepository(db_path)

    assert primeiro_resumo["novos"] == 2
    assert segundo_resumo["novos"] == 0
    assert [item["id"] for item in repository.listar()] == ["json-1", "json-2"]


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
    repository.salvar([agendamento_base()])
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

    agenda = repository.listar()
    assert "remarcado" in resposta.lower()
    assert len(agenda) == 1
    assert agenda[0]["id"] == "agenda-1"
    assert agenda[0]["data"] == "2026-06-19"
    assert agenda[0]["horario"] == "14:30"


def test_remarcacao_adiciona_remarcado_em_e_historico(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("trocar horário")
    flow.receber("14999999999")
    flow.receber("1")
    flow.receber("19/06/2026")
    flow.receber("tarde")
    flow.receber("14:30")
    flow.receber("sim")

    agendamento = repository.listar()[0]
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
    repository.salvar(
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
    repository.salvar([agendamento_base()] + ocupados)
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
    repository.salvar([agendamento_base()])
    flow = AtendimentoFlow(repository, hoje=date(2026, 6, 18))

    flow.iniciar()
    flow.receber("remarcar")
    flow.receber("14999999999")
    flow.receber("1")
    flow.receber("19/06/2026")
    flow.receber("tarde")
    flow.receber("14:30")
    resposta = flow.receber("não")

    agendamento = repository.listar()[0]
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
    assert validar_data_agendamento("hoje", hoje=HOJE)[0] == "2026-06-17"
    assert validar_data_agendamento("17/06/2026", hoje=HOJE)[0] == "2026-06-17"


def test_data_de_amanha_deve_ser_aceita():
    assert validar_data_agendamento("amanhã", hoje=HOJE)[0] == "2026-06-18"
    assert validar_data_agendamento("18/06/2026", hoje=HOJE)[0] == "2026-06-18"


def test_data_invalida_deve_ser_rejeitada():
    assert validar_data_agendamento("31/02/2026", hoje=HOJE)[0] is None
    assert validar_data_agendamento("2026-06-17", hoje=HOJE)[0] is None


def test_telefone_normalizado_remove_mascara():
    assert normalizar_telefone("(14) 99999-9999") == "14999999999"
    assert normalizar_telefone("14 99999 9999") == "14999999999"


def test_telefone_whatsapp_normalizado_para_client_id():
    assert normalizar_telefone_whatsapp("+55 (14) 99999-9999") == "5514999999999"
    assert normalizar_telefone_whatsapp("whatsapp:+5514999999999") == "5514999999999"
    assert normalizar_telefone_whatsapp("14999999999") == "5514999999999"


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


def test_engine_padrao_usa_sqlite_e_persiste_sessao(tmp_path):
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")
    config["storage"] = {"type": "sqlite", "path": str(tmp_path / "agenda.db")}

    engine = ConversationEngine(config=config)
    engine.start("+55 (14) 99999-9999")
    engine.process_message("+55 (14) 99999-9999", "agendar")

    reaberta = ConversationEngine(config=config)

    assert isinstance(engine.agenda_repository, SQLiteAgendaRepository)
    assert reaberta.session_store.get_or_create("whatsapp:+5514999999999").etapa == "dia"


def test_engine_boas_vindas_persistem_no_sqlite_apos_recriar_engine(tmp_path):
    db_path = tmp_path / "agenda.db"
    repository = SQLiteAgendaRepository(db_path)
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))
    sender_id = "whatsapp:+5514999999999"

    primeira = engine.process_message(sender_id, "agendar")
    estado_salvo = engine.session_store.get_or_create(sender_id)
    reaberta = ConversationEngine(agenda_repository=SQLiteAgendaRepository(db_path), hoje=date(2026, 6, 18))
    segunda = reaberta.process_message(sender_id, "amanha")
    estado_reaberto = reaberta.session_store.get_or_create(sender_id)

    assert "Seja bem-vindo" in primeira
    assert estado_salvo.boas_vindas_enviada is True
    assert "Seja bem-vindo" not in segunda
    assert estado_reaberto.boas_vindas_enviada is True


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
    assert repository.listar()[0]["data"] == "2026-06-19"
    assert repository.listar()[0]["telefone"] == "14999999999"


def test_engine_sessao_encerrada_oferece_novo_atendimento(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "agendar")
    cancelada = engine.process_message("cliente_1", "cancelar")
    resposta = engine.process_message("cliente_1", "opa")

    assert "cancelado" in cancelada.lower()
    assert engine.is_finished("cliente_1") is True
    assert "novo atendimento" in resposta
    assert "Atendimento já encerrado." not in resposta


def test_engine_sessao_encerrada_comando_1_abre_novo_atendimento(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "agendar")
    engine.process_message("cliente_1", "cancelar")
    resposta = engine.process_message("cliente_1", "1")

    assert "agendar" in resposta
    assert engine.is_finished("cliente_1") is False
    assert engine.session_store.get_or_create("cliente_1").etapa == "escolha_inicial"


def test_engine_sessao_encerrada_novo_atendimento_reinicia(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "agendar")
    engine.process_message("cliente_1", "cancelar")
    resposta = engine.process_message("cliente_1", "novo atendimento")

    assert "agendar" in resposta
    assert engine.is_finished("cliente_1") is False
    assert engine.session_store.get_or_create("cliente_1").erros_invalidos_consecutivos == 0


def test_engine_agendamento_whatsapp_usa_sender_id_como_telefone(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))
    sender_id = "whatsapp:+5514999999999"

    engine.start(sender_id)
    mensagens = ["agendar", "amanhã", "corte", "não", "manha", "10:00", "Marcos Eduardo"]
    respostas = [engine.process_message(sender_id, mensagem) for mensagem in mensagens]

    assert "Me informe seu telefone" not in respostas[-1]
    assert engine.session_store.get_or_create(sender_id).etapa == "confirmacao"
    assert "Telefone: 5514999999999" in respostas[-1]

    resposta_final = engine.process_message(sender_id, "sim")
    agenda = repository.listar()

    assert "Agendamento confirmado" in resposta_final
    assert len(agenda) == 1
    assert agenda[0]["cliente_id"] == "5514999999999"
    assert agenda[0]["telefone"] == "5514999999999"
    assert agenda[0]["telefone_normalizado"] == "5514999999999"


def test_engine_conflito_de_horario_retorna_resposta_compreensivel(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.adicionar_agendamento(agendamento_base())
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))
    sender_id = "whatsapp:+5514888888888"
    state = ConversationState(
        etapa="confirmacao",
        data="2026-06-18",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        horario="15:00",
        profissional="Marcos",
        nome="Cliente Conflito",
        telefone="5514888888888",
        boas_vindas_enviada=True,
    )
    engine.session_store.save(sender_id, state)

    resposta = engine.process_message(sender_id, "sim")

    assert "ocupado" in resposta.lower() or "indispon" in resposta.lower()
    assert len(repository.listar()) == 1


def test_engine_processa_consulta_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    assert "telefone" in engine.process_message("cliente_1", "consultar")
    resposta = engine.process_message("cliente_1", "(14) 99999-9999")

    assert "Corte com Marcos em 18/06/2026 às 15:00" in resposta


def test_engine_consulta_whatsapp_usa_sender_id_sem_pedir_telefone(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.salvar([agendamento_base(telefone="+55 (14) 99999-9999")])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))
    sender_id = "whatsapp:+5514999999999"

    engine.start(sender_id)
    resposta = engine.process_message(sender_id, "consultar")

    assert "Digite o telefone" not in resposta
    assert "Corte com Marcos em 18/06/2026 às 15:00" in resposta


def test_engine_processa_cancelamento_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "cancelar")
    engine.process_message("cliente_1", "14999999999")
    engine.process_message("cliente_1", "1")
    resposta = engine.process_message("cliente_1", "sim")

    assert "cancelado" in resposta.lower()
    assert repository.listar()[0]["status"] == "cancelado"


def test_engine_cancelamento_whatsapp_usa_sender_id_sem_pedir_telefone(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.salvar([agendamento_base(telefone="+55 (14) 99999-9999")])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))
    sender_id = "whatsapp:+5514999999999"

    engine.start(sender_id)
    resposta_lista = engine.process_message(sender_id, "cancelar")
    engine.process_message(sender_id, "1")
    resposta = engine.process_message(sender_id, "sim")

    assert "Digite o telefone" not in resposta_lista
    assert "ativos" in resposta_lista
    assert "cancelado" in resposta.lower()
    assert repository.buscar_agendamento_por_id("agenda-1")["status"] == "cancelado"


def test_engine_processa_remarcacao_por_telefone(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base()])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))

    engine.start("cliente_1")
    engine.process_message("cliente_1", "remarcar")
    engine.process_message("cliente_1", "14999999999")
    engine.process_message("cliente_1", "1")
    engine.process_message("cliente_1", "19/06/2026")
    engine.process_message("cliente_1", "tarde")
    engine.process_message("cliente_1", "14:30")
    resposta = engine.process_message("cliente_1", "sim")

    agendamento = repository.listar()[0]
    assert "remarcado" in resposta.lower()
    assert agendamento["data"] == "2026-06-19"
    assert agendamento["horario"] == "14:30"


def test_engine_remarcacao_whatsapp_usa_sender_id_sem_pedir_telefone(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    repository.salvar([agendamento_base(telefone="+55 (14) 99999-9999")])
    engine = ConversationEngine(agenda_repository=repository, hoje=date(2026, 6, 18))
    sender_id = "whatsapp:+5514999999999"

    engine.start(sender_id)
    resposta_lista = engine.process_message(sender_id, "remarcar")
    engine.process_message(sender_id, "1")
    engine.process_message(sender_id, "19/06/2026")
    engine.process_message(sender_id, "tarde")
    engine.process_message(sender_id, "14:30")
    resposta = engine.process_message(sender_id, "sim")

    agendamento = repository.buscar_agendamento_por_id("agenda-1")
    assert "Digite o telefone" not in resposta_lista
    assert "ativos" in resposta_lista
    assert "remarcado" in resposta.lower()
    assert agendamento["telefone_normalizado"] == "5514999999999"
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


def test_fake_whatsapp_channel_aceita_payload_com_from_ou_telefone():
    channel = FakeWhatsAppChannel()

    por_from = channel.build_incoming_from_payload(
        {"from": "whatsapp:+5514999999999", "message": "quero agendar"}
    )
    por_telefone = channel.build_incoming_payload(
        {"telefone": "+55 (14) 99999-9999", "mensagem": "cancelar"}
    )

    assert por_from.sender_id == "5514999999999"
    assert por_from.text == "quero agendar"
    assert por_telefone.sender_id == "5514999999999"
    assert por_telefone.text == "cancelar"


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
    assert "Não encontrei agendamentos ativos" in resposta_2
    assert engine.session_store.get_or_create("14999999999").etapa == "dia"
    assert engine.session_store.get_or_create("14888888888").etapa == "encerrado"


def test_webhook_health_retorna_ok(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "atendente-whatsapp",
        "storage": "sqlite",
    }


def test_webhook_whatsapp_bloqueia_sem_webhook_api_key_configurada(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)

    response = client.post(
        "/webhook/whatsapp",
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    assert response.status_code == 500
    assert response.json() == {"ok": False, "error": "WEBHOOK_API_KEY nao configurada."}


def test_webhook_whatsapp_bloqueia_webhook_api_key_vazia(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setenv("WEBHOOK_API_KEY", "   ")

    response = client.post(
        "/webhook/whatsapp",
        headers={"X-API-Key": "   "},
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    assert response.status_code == 500
    assert response.json() == {"ok": False, "error": "WEBHOOK_API_KEY nao configurada."}


def test_webhook_whatsapp_rejeita_sem_header_quando_api_key_configurada(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setenv("WEBHOOK_API_KEY", "segredo")

    response = client.post(
        "/webhook/whatsapp",
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "unauthorized"}


def test_webhook_whatsapp_rejeita_api_key_errada(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setenv("WEBHOOK_API_KEY", "segredo")

    response = client.post(
        "/webhook/whatsapp",
        headers={"X-API-Key": "errada"},
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "unauthorized"}


def test_webhook_whatsapp_aceita_api_key_correta(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setenv("WEBHOOK_API_KEY", "segredo")

    response = client.post(
        "/webhook/whatsapp",
        headers={"X-API-Key": "segredo"},
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_webhook_whatsapp_aceita_from_e_message(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    response = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["to"] == "5514999999999"
    assert "O que você deseja fazer" in body["reply"]
    assert "Qual dia" not in body["reply"]
    assert body["human_requested"] is False


def test_webhook_whatsapp_aceita_telefone_e_mensagem(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    response = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"telefone": "+55 (14) 99999-9999", "mensagem": "agendar"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["to"] == "5514999999999"
    assert "O que você deseja fazer" in body["reply"]
    assert "Qual dia" not in body["reply"]


def test_webhook_whatsapp_primeiro_contato_recebe_boas_vindas(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    response = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    body = response.json()
    assert response.status_code == 200
    assert "O que você deseja fazer" in body["reply"]
    assert "Qual dia" not in body["reply"]
    state = webhook_app.state.engine.session_store.get_or_create("5514999999999")
    assert state.boas_vindas_enviada is True
    assert state.telefone == "5514999999999"
    assert state.etapa == "escolha_inicial"


def test_webhook_nao_forca_boas_vindas_para_false_apos_start():
    codigo = inspect.getsource(webhook_api_module._processar_mensagem_webhook)

    assert "boas_vindas_enviada = False" not in codigo


def test_webhook_whatsapp_segunda_mensagem_nao_repete_boas_vindas(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "oi"},
    )
    response = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    body = response.json()
    assert response.status_code == 200
    assert "Seja bem-vindo" not in body["reply"]
    assert "Qual dia" in body["reply"]
    assert webhook_app.state.engine.session_store.get_or_create("5514999999999").boas_vindas_enviada is True


def test_webhook_whatsapp_cliente_reinicia_apos_atendimento_cancelado(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, hoje=date(2026, 6, 18), monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    for payload in [
        {"from": "whatsapp:+5514999999999", "message": "oi", "message_id": "restart-0"},
        {"from": "whatsapp:+5514999999999", "message": "agendar", "message_id": "restart-1"},
        {"from": "whatsapp:+5514999999999", "message": "cancelar", "message_id": "restart-2"},
    ]:
        response = client.post("/webhook/whatsapp", headers=headers, json=payload)
        assert response.status_code == 200

    bloqueada = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "opa", "message_id": "restart-3"},
    )
    reiniciada = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "1", "message_id": "restart-4"},
    )

    assert "novo atendimento" in bloqueada.json()["reply"]
    assert "Atendimento já encerrado." not in bloqueada.json()["reply"]
    assert "agendar" in reiniciada.json()["reply"]
    assert webhook_app.state.engine.session_store.get_or_create("5514999999999").etapa == "escolha_inicial"


def test_webhook_whatsapp_dois_numeros_recebem_boas_vindas_separadas(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    primeira = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )
    segunda = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514888888888", "message": "agendar"},
    )

    assert "O que você deseja fazer" in primeira.json()["reply"]
    assert "O que você deseja fazer" in segunda.json()["reply"]
    assert "Qual dia" not in primeira.json()["reply"]
    assert "Qual dia" not in segunda.json()["reply"]


def test_webhook_whatsapp_duas_sessoes_nao_misturam_estado(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    primeira = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "oi"},
    )
    segunda = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514888888888", "message": "oi"},
    )
    client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar"},
    )

    engine = webhook_app.state.engine
    estado_1 = engine.session_store.get_or_create("5514999999999")
    estado_2 = engine.session_store.get_or_create("5514888888888")

    assert primeira.json()["to"] == "5514999999999"
    assert segunda.json()["to"] == "5514888888888"
    assert estado_1.etapa == "dia"
    assert estado_2.etapa == "escolha_inicial"


def test_webhook_whatsapp_agendamento_salva_no_sqlite(tmp_path, monkeypatch):
    client, repository = webhook_client(tmp_path, hoje=date(2026, 6, 18), monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)
    payloads = [
        {"from": "whatsapp:+5514999999999", "message": "oi"},
        {"from": "whatsapp:+5514999999999", "message": "agendar"},
        {"from": "whatsapp:+5514999999999", "message": "amanhã"},
        {"from": "whatsapp:+5514999999999", "message": "corte"},
        {"from": "whatsapp:+5514999999999", "message": "não"},
        {"from": "whatsapp:+5514999999999", "message": "manha"},
        {"from": "whatsapp:+5514999999999", "message": "10:00"},
        {"from": "whatsapp:+5514999999999", "message": "Eduardo Cliente"},
        {"from": "whatsapp:+5514999999999", "message": "sim"},
    ]

    responses = [client.post("/webhook/whatsapp", headers=headers, json=payload) for payload in payloads]
    agenda = repository.listar()

    assert responses[-1].status_code == 200
    assert "Agendamento confirmado" in responses[-1].json()["reply"]
    assert len(agenda) == 1
    assert agenda[0]["nome"] == "Eduardo Cliente"
    assert agenda[0]["telefone"] == "5514999999999"
    assert agenda[0]["telefone_normalizado"] == "5514999999999"
    assert agenda[0]["cliente_id"] == "5514999999999"
    assert agenda[0]["data"] == "2026-06-19"
    assert agenda[0]["horario"] == "10:00"


def test_webhook_whatsapp_mensagem_duplicada_com_id_nao_reprocessa(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)
    payload = {"from": "whatsapp:+5514999999999", "message": "agendar", "message_id": "generic-1"}

    client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "oi", "message_id": "generic-start"},
    )
    primeira = client.post("/webhook/whatsapp", headers=headers, json=payload)
    segunda = client.post("/webhook/whatsapp", headers=headers, json=payload)

    assert primeira.status_code == 200
    assert primeira.json()["ok"] is True
    assert segunda.status_code == 200
    assert segunda.json()["duplicate"] is True
    assert segunda.json()["processed"] == 0
    assert webhook_app.state.engine.session_store.get_or_create("5514999999999").etapa == "dia"


def test_webhook_whatsapp_sem_id_com_timestamp_diferente_nao_deduplica(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "oi", "timestamp": "start"},
    )
    primeira = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar", "timestamp": "100"},
    )
    segunda = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "agendar", "timestamp": "101"},
    )

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json().get("duplicate") is None
    assert segunda.json()["ok"] is True


def test_webhook_whatsapp_sem_id_com_mesmo_timestamp_deduplica(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)
    payload = {"from": "whatsapp:+5514999999999", "message": "agendar", "timestamp": "100"}

    primeira = client.post("/webhook/whatsapp", headers=headers, json=payload)
    segunda = client.post("/webhook/whatsapp", headers=headers, json=payload)

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json()["duplicate"] is True
    assert segunda.json()["processed"] == 0


def test_webhook_whatsapp_confirmacao_duplicada_nao_cria_dois_agendamentos(tmp_path, monkeypatch):
    client, repository = webhook_client(tmp_path, hoje=date(2026, 6, 18), monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)
    payloads = [
        {"from": "whatsapp:+5514999999999", "message": "oi", "message_id": "a0"},
        {"from": "whatsapp:+5514999999999", "message": "agendar", "message_id": "a1"},
        {"from": "whatsapp:+5514999999999", "message": "amanha", "message_id": "a2"},
        {"from": "whatsapp:+5514999999999", "message": "corte", "message_id": "a3"},
        {"from": "whatsapp:+5514999999999", "message": "nao", "message_id": "a4"},
        {"from": "whatsapp:+5514999999999", "message": "manha", "message_id": "a5"},
        {"from": "whatsapp:+5514999999999", "message": "10:00", "message_id": "a6"},
        {"from": "whatsapp:+5514999999999", "message": "Eduardo Cliente", "message_id": "a7"},
        {"from": "whatsapp:+5514999999999", "message": "sim", "message_id": "a8"},
    ]

    for payload in payloads:
        response = client.post("/webhook/whatsapp", headers=headers, json=payload)
        assert response.status_code == 200
    duplicada = client.post("/webhook/whatsapp", headers=headers, json=payloads[-1])

    assert duplicada.json()["duplicate"] is True
    assert len(repository.listar()) == 1


def test_webhook_whatsapp_cancelamento_duplicado_nao_quebra(tmp_path, monkeypatch):
    client, repository = webhook_client(tmp_path, hoje=date(2026, 6, 18), monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)
    repository.adicionar_agendamento(agendamento_base(telefone="+55 (14) 99999-9999"))

    for payload in [
        {"from": "whatsapp:+5514999999999", "message": "oi", "message_id": "c0"},
        {"from": "whatsapp:+5514999999999", "message": "cancelar", "message_id": "c1"},
        {"from": "whatsapp:+5514999999999", "message": "1", "message_id": "c2"},
        {"from": "whatsapp:+5514999999999", "message": "sim", "message_id": "c3"},
    ]:
        response = client.post("/webhook/whatsapp", headers=headers, json=payload)
        assert response.status_code == 200
    duplicada = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "sim", "message_id": "c3"},
    )

    assert duplicada.json()["duplicate"] is True
    assert repository.buscar_agendamento_por_id("agenda-1")["status"] == "cancelado"


def test_webhook_whatsapp_remarcacao_duplicada_nao_cria_inconsistencia(tmp_path, monkeypatch):
    client, repository = webhook_client(tmp_path, hoje=date(2026, 6, 18), monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)
    repository.adicionar_agendamento(agendamento_base(telefone="+55 (14) 99999-9999"))

    for payload in [
        {"from": "whatsapp:+5514999999999", "message": "oi", "message_id": "r0"},
        {"from": "whatsapp:+5514999999999", "message": "remarcar", "message_id": "r1"},
        {"from": "whatsapp:+5514999999999", "message": "1", "message_id": "r2"},
        {"from": "whatsapp:+5514999999999", "message": "19/06/2026", "message_id": "r3"},
        {"from": "whatsapp:+5514999999999", "message": "tarde", "message_id": "r4"},
        {"from": "whatsapp:+5514999999999", "message": "14:30", "message_id": "r5"},
        {"from": "whatsapp:+5514999999999", "message": "sim", "message_id": "r6"},
    ]:
        response = client.post("/webhook/whatsapp", headers=headers, json=payload)
        assert response.status_code == 200
    duplicada = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "sim", "message_id": "r6"},
    )
    agendamento = repository.buscar_agendamento_por_id("agenda-1")

    assert duplicada.json()["duplicate"] is True
    assert len(repository.listar()) == 1
    assert agendamento["data"] == "2026-06-19"
    assert agendamento["horario"] == "14:30"


def test_webhook_whatsapp_pedido_humano_retorna_flag(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "oi"},
    )
    response = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999", "message": "humano"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["to"] == "5514999999999"
    assert body["human_requested"] is True
    assert "chamar" in body["reply"].lower() or "encaminhar" in body["reply"].lower()


def test_webhook_whatsapp_sem_telefone_retorna_erro_claro(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    response = client.post("/webhook/whatsapp", headers=headers, json={"message": "agendar"})

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "Payload sem telefone de origem."}


def test_webhook_whatsapp_sem_mensagem_retorna_erro_claro(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    headers = webhook_auth_headers(monkeypatch)

    response = client.post(
        "/webhook/whatsapp",
        headers=headers,
        json={"from": "whatsapp:+5514999999999"},
    )

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "Payload sem mensagem."}


def test_webhook_meta_verify_token_correto_retorna_challenge(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setenv("META_WHATSAPP_VERIFY_TOKEN", "verify-local")

    response = client.get(
        "/webhook/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-local",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_webhook_meta_verify_token_errado_retorna_403(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setenv("META_WHATSAPP_VERIFY_TOKEN", "verify-local")

    response = client.get(
        "/webhook/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "errado",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"ok": False, "error": "Meta webhook verification failed."}


def test_webhook_meta_mensagem_texto_processa_conversa(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    fake_meta = FakeMetaWhatsAppClient()
    webhook_app.state.meta_client = fake_meta

    response = client.post("/webhook/meta", json=meta_text_payload("agendar"))

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    assert webhook_app.state.engine.session_store.get_or_create("5514999999999").etapa == "escolha_inicial"


def test_webhook_meta_ignora_status_sem_mensagem(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    fake_meta = FakeMetaWhatsAppClient()
    webhook_app.state.meta_client = fake_meta

    response = client.post("/webhook/meta", json=meta_status_payload())

    assert response.status_code == 200
    assert response.json() == {"ok": True, "processed": 0, "ignored": True}
    assert fake_meta.calls == []


def test_webhook_meta_chama_client_com_telefone_e_resposta(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    fake_meta = FakeMetaWhatsAppClient()
    webhook_app.state.meta_client = fake_meta

    response = client.post("/webhook/meta", json=meta_text_payload("agendar"))

    assert response.status_code == 200
    assert response.json()["sent"] == 1
    assert fake_meta.calls[0]["to"] == "5514999999999"
    assert "O que você deseja fazer" in fake_meta.calls[0]["text"]
    assert "Qual dia" not in fake_meta.calls[0]["text"]


def test_webhook_meta_nao_processa_mensagem_duplicada(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)
    fake_meta = FakeMetaWhatsAppClient()
    webhook_app.state.meta_client = fake_meta
    payload = meta_text_payload("agendar", message_id="wamid.duplicado")

    primeira = client.post("/webhook/meta", json=payload)
    segunda = client.post("/webhook/meta", json=payload)

    assert primeira.status_code == 200
    assert primeira.json()["processed"] == 1
    assert segunda.status_code == 200
    assert segunda.json()["processed"] == 0
    assert segunda.json()["duplicated"] == 1
    assert len(fake_meta.calls) == 1


def test_webhook_meta_sem_variaveis_retorna_erro_claro_sem_quebrar(tmp_path, monkeypatch):
    client, _repository = webhook_client(tmp_path, monkeypatch=monkeypatch)

    response = client.post("/webhook/meta", json=meta_text_payload("agendar"))

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["processed"] == 1
    assert body["send_errors"][0]["ok"] is False
    assert body["send_errors"][0]["error"] == "Configuracao da Meta incompleta."
    assert set(body["send_errors"][0]["missing"]) == {
        "META_WHATSAPP_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
    }


def test_terminal_continua_usando_mesma_engine_via_canal():
    codigo = inspect.getsource(run_terminal_app)

    assert "TerminalChannel" in codigo
    assert "engine.process_message" in codigo
    assert "OutgoingMessage" in codigo


def test_admin_listar_agenda_por_data_retorna_apenas_agendados(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="ativo"),
            agendamento_base(id="cancelado", status="cancelado", cancelado_em="2026-06-18T10:00:00"),
            agendamento_base(id="outra-data", data="2026-06-19"),
        ]
    )

    agendamentos = reports.listar_agendamentos_por_data("2026-06-18", repository)

    assert [agendamento["id"] for agendamento in agendamentos] == ["ativo"]


def test_admin_ordenacao_de_agendamentos_usa_nome_como_desempate():
    agendamentos = [
        agendamento_base(id="bia", nome="Bia"),
        agendamento_base(id="ana", nome="Ana"),
    ]

    ordenados = reports.ordenar_agendamentos(agendamentos)

    assert [agendamento["id"] for agendamento in ordenados] == ["ana", "bia"]


def test_admin_agenda_hoje_ignora_cancelados(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="ativo", data="2026-06-18"),
            agendamento_base(id="cancelado", data="2026-06-18", status="cancelado"),
        ]
    )

    agendamentos = reports.listar_agendamentos_hoje(repository, hoje=date(2026, 6, 18))

    assert len(agendamentos) == 1
    assert agendamentos[0]["id"] == "ativo"


def test_admin_agenda_amanha_funciona(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="hoje", data="2026-06-18"),
            agendamento_base(id="amanha", data="2026-06-19"),
        ]
    )

    agendamentos = reports.listar_agendamentos_amanha(repository, hoje=date(2026, 6, 18))

    assert [agendamento["id"] for agendamento in agendamentos] == ["amanha"]


def test_admin_listar_por_profissional_funciona(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="marcos", profissional="Marcos"),
            agendamento_base(id="julio", profissional="Julio"),
            agendamento_base(id="marcos-cancelado", profissional="Marcos", status="cancelado"),
        ]
    )

    agendamentos = reports.listar_agendamentos_por_profissional("Marcos", repository)

    assert [agendamento["id"] for agendamento in agendamentos] == ["marcos"]


def test_admin_cancelados_aparecem_no_relatorio_de_cancelados(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="ativo"),
            agendamento_base(id="cancelado", status="cancelado", cancelado_em="2026-06-18T10:00:00"),
        ]
    )

    cancelados = reports.listar_agendamentos_cancelados(repository)

    assert [agendamento["id"] for agendamento in cancelados] == ["cancelado"]


def test_admin_solicitacoes_loja_sao_listadas(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "solicitacoes.json")
    repository.salvar(
        [
            {
                "nome": "Eduardo",
                "telefone": "14999999999",
                "categoria": "orcamento",
                "descricao": "Quero um orçamento",
                "criado_em": "2026-06-18T10:00:00",
                "status": "novo",
            }
        ]
    )

    solicitacoes = reports.listar_solicitacoes_loja(repository)

    assert solicitacoes[0]["nome"] == "Eduardo"
    assert solicitacoes[0]["descricao"] == "Quero um orçamento"


def test_admin_solicitacoes_humano_sao_lidas_das_sessoes_sqlite(tmp_path):
    repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    store = SQLiteSessionStore(tmp_path / "agenda.db")
    store.save(
        "whatsapp:+5514999999999",
        ConversationState(
            etapa="encerrado",
            nome="Eduardo",
            telefone="5514999999999",
            humano_solicitado=True,
            etapa_antes_humano="horario",
        ),
        finished=True,
    )

    solicitacoes = reports.listar_solicitacoes_humano(repository)

    assert len(solicitacoes) == 1
    assert solicitacoes[0]["tipo"] == "humano"
    assert solicitacoes[0]["nome"] == "Eduardo"
    assert solicitacoes[0]["telefone"] == "5514999999999"
    assert solicitacoes[0]["whatsapp"] == "whatsapp:+5514999999999"
    assert solicitacoes[0]["etapa_origem"] == "horario"
    assert solicitacoes[0]["status"] == "pendente"


def test_admin_solicitacoes_atendimento_combina_humano_e_loja(tmp_path):
    agenda_repository = SQLiteAgendaRepository(tmp_path / "agenda.db")
    store = SQLiteSessionStore(tmp_path / "agenda.db")
    store.save(
        "whatsapp:+5514999999999",
        ConversationState(
            etapa="encerrado",
            telefone="5514999999999",
            humano_solicitado=True,
            etapa_antes_humano="dia",
        ),
        finished=True,
    )
    solicitacoes_repository = JsonAgendaRepository(tmp_path / "solicitacoes.json")
    solicitacoes_repository.salvar(
        [{"nome": "Cliente Loja", "telefone": "14999999999", "descricao": "Quero orçamento"}]
    )

    solicitacoes = reports.listar_solicitacoes_atendimento(agenda_repository, solicitacoes_repository)

    assert [item["tipo"] for item in solicitacoes] == ["humano", "loja"]


def test_admin_resumo_do_dia_conta_servicos_corretamente(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="corte-1", servico="corte", horario="09:00"),
            agendamento_base(id="corte-2", servico="corte", horario="10:00"),
            agendamento_base(id="barba", servico="barba", horario="11:00"),
            agendamento_base(id="cancelado", servico="barba", status="cancelado"),
        ]
    )

    resumo = reports.gerar_resumo_do_dia("2026-06-18", repository)

    assert resumo["servicos"] == {"corte": 2, "barba": 1}
    assert resumo["total_agendamentos_ativos"] == 3
    assert resumo["total_cancelados"] == 1


def test_admin_resumo_do_dia_conta_profissionais_corretamente(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="marcos-1", profissional="Marcos", horario="09:00"),
            agendamento_base(id="marcos-2", profissional="Marcos", horario="10:00"),
            agendamento_base(id="julio", profissional="Julio", horario="11:00"),
        ]
    )

    resumo = reports.gerar_resumo_do_dia("2026-06-18", repository)

    assert resumo["por_profissional"] == {"Marcos": 2, "Julio": 1}
    assert resumo["profissional_mais_atendimentos"] == "Marcos"
    assert resumo["primeiro_horario"] == "09:00"
    assert resumo["ultimo_horario"] == "11:00"


def test_admin_horarios_disponiveis_por_data_periodo_funcionam(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar([agendamento_base(data="2026-06-18", horario="14:00", profissional="Marcos")])
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    horarios = reports.listar_horarios_disponiveis(
        data="2026-06-18",
        periodo="tarde",
        profissional="Marcos",
        agenda_repository=repository,
        config=config,
        servico="corte",
    )

    assert "14:00" not in horarios["Marcos"]
    assert "14:30" in horarios["Marcos"]


def test_admin_formatador_lista_vazia_retorna_mensagem_clara():
    assert formatters.formatar_lista_agendamentos([]) == "Nenhum agendamento encontrado."
    assert formatters.formatar_tabela_solicitacoes([]) == "Nenhuma solicitação encontrada."
    assert formatters.formatar_horarios_disponiveis({}) == "Nenhum horário disponível."


def test_admin_formatador_agenda_mostra_nome_servico_profissional_e_telefone():
    agendamento = agendamento_base(
        nome="Eduardo",
        servico="corte",
        profissional="Marcos",
        telefone="14999999999",
    )

    formatado = formatters.formatar_agendamento(agendamento)

    assert formatado["cliente"] == "Eduardo"
    assert formatado["serviço"] == "corte"
    assert formatado["profissional"] == "Marcos"
    assert formatado["telefone"] == "14999999999"


def test_admin_formatador_tabela_agenda_retorna_colunas_esperadas():
    tabela = formatters.formatar_tabela_agendamentos([agendamento_base()])

    assert set(tabela[0]) == {
        "Data",
        "Horário",
        "Serviço",
        "Profissional",
        "Cliente",
        "Telefone",
        "Status",
    }


def test_admin_formatar_contagem_tabela_ordena_e_aceita_colunas_customizadas():
    tabela = formatters.formatar_contagem_tabela(
        {"barba": 1, "corte": 3, "corte + barba": 2},
        nome_coluna="Serviço",
        valor_coluna="Total",
    )

    assert tabela == [
        {"Serviço": "corte", "Total": 3},
        {"Serviço": "corte + barba", "Total": 2},
        {"Serviço": "barba", "Total": 1},
    ]
    assert formatters.formatar_contagem_tabela({}) == []
    assert formatters.formatar_contagem_tabela(None) == []


def test_script_gerar_dados_demo_cria_agenda_nao_vazia(tmp_path):
    agenda_path = tmp_path / "agenda.json"
    solicitacoes_path = tmp_path / "solicitacoes.json"
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    agenda, solicitacoes = gerar_dados_demo(
        agenda_path=agenda_path,
        solicitacoes_path=solicitacoes_path,
        config=config,
        hoje=date(2026, 6, 18),
    )

    assert agenda
    assert solicitacoes
    assert json.loads(agenda_path.read_text(encoding="utf-8")) == agenda
    assert json.loads(solicitacoes_path.read_text(encoding="utf-8")) == solicitacoes


def test_script_gerar_dados_demo_preserva_dados_nao_demo(tmp_path):
    agenda_path = tmp_path / "agenda.json"
    solicitacoes_path = tmp_path / "solicitacoes.json"
    agenda_path.write_text(
        json.dumps(
            [
                agendamento_base(id="real-1"),
                agendamento_base(id="demo-agenda-antigo", origem="demo"),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    solicitacoes_path.write_text(
        json.dumps(
            [
                {"id": "real-solicitacao", "nome": "Cliente Local"},
                {"id": "demo-solicitacao-antiga", "origem": "demo"},
                {"id": "sol-demo-legado", "nome": "Demo Antiga"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    agenda, solicitacoes = gerar_dados_demo(
        agenda_path=agenda_path,
        solicitacoes_path=solicitacoes_path,
        config=config,
        hoje=date(2026, 6, 18),
    )

    assert any(item["id"] == "real-1" for item in agenda)
    assert not any(item["id"] == "demo-agenda-antigo" for item in agenda)
    assert any(item["id"] == "real-solicitacao" for item in solicitacoes)
    assert not any(item["id"] == "demo-solicitacao-antiga" for item in solicitacoes)
    assert not any(item["id"] == "sol-demo-legado" for item in solicitacoes)


def test_dados_demo_incluem_hoje_futuro_cancelamento_remarcacao_e_origem():
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    agenda = criar_agenda_demo(config, hoje=date(2026, 6, 18))
    datas = {agendamento["data"] for agendamento in agenda}
    servicos = {agendamento["servico"] for agendamento in agenda}

    assert "2026-06-18" in datas
    assert any(data > "2026-06-18" for data in datas)
    assert {"corte", "barba", "corte + barba"}.issubset(servicos)
    assert any(agendamento["status"] == "cancelado" for agendamento in agenda)
    assert any(agendamento.get("remarcado_em") for agendamento in agenda)
    assert all(agendamento.get("origem") == "demo" for agendamento in agenda)


def test_dados_demo_possuem_status_agendado_e_cancelado():
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    agenda = criar_agenda_demo(config, hoje=date(2026, 6, 18))
    status = {agendamento["status"] for agendamento in agenda}

    assert "agendado" in status
    assert "cancelado" in status


def test_dados_demo_nao_usam_nomes_reais_sensiveis():
    nomes_reais_do_projeto = {"Eduardo", "Marcos Eduardo"}

    assert not nomes_reais_do_projeto.intersection(CLIENTES_FICTICIOS)


def test_resumo_do_dia_funciona_com_dados_demo(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")
    agenda = criar_agenda_demo(config, hoje=date(2026, 6, 18))
    repository.salvar(agenda)

    resumo = reports.gerar_resumo_do_dia("2026-06-18", repository)

    assert resumo["total_agendamentos_ativos"] >= 1
    assert resumo["servicos"]
    assert resumo["por_profissional"]


def test_limpar_dados_zera_agenda_e_solicitacoes(tmp_path):
    agenda_path = tmp_path / "agenda.json"
    solicitacoes_path = tmp_path / "solicitacoes.json"
    agenda_path.write_text('[{"id": "1"}]', encoding="utf-8")
    solicitacoes_path.write_text('[{"id": "2"}]', encoding="utf-8")

    limpar_dados(agenda_path=agenda_path, solicitacoes_path=solicitacoes_path)

    assert json.loads(agenda_path.read_text(encoding="utf-8")) == []
    assert json.loads(solicitacoes_path.read_text(encoding="utf-8")) == []


def test_limpar_dados_sqlite_remove_sessoes_com_pedido_humano(tmp_path):
    db_path = tmp_path / "agenda.db"
    repository = SQLiteAgendaRepository(db_path)
    repository.salvar([agendamento_base()])
    store = SQLiteSessionStore(db_path)
    store.save(
        "whatsapp:+5514999999999",
        ConversationState(
            etapa="encerrado",
            telefone="5514999999999",
            humano_solicitado=True,
            etapa_antes_humano="horario",
        ),
        finished=True,
    )

    limpar_dados(agenda_path=db_path, solicitacoes_path=tmp_path / "solicitacoes.json")

    assert repository.listar() == []
    assert reports.listar_solicitacoes_humano(repository) == []


def test_relatorios_continuam_ignorando_cancelados_na_agenda_ativa(tmp_path):
    repository = JsonAgendaRepository(tmp_path / "agenda.json")
    repository.salvar(
        [
            agendamento_base(id="ativo", status="agendado"),
            agendamento_base(id="cancelado", status="cancelado"),
        ]
    )

    agendamentos = reports.listar_agendamentos_por_data("2026-06-18", repository)

    assert [agendamento["id"] for agendamento in agendamentos] == ["ativo"]


def test_painel_importa_sem_executar_erro_grave():
    import app.admin_dashboard as admin_dashboard

    assert callable(admin_dashboard.main)


def test_painel_tem_fallback_para_formatar_contagem_tabela(monkeypatch):
    import app.admin_dashboard as admin_dashboard

    monkeypatch.delattr(formatters, "formatar_contagem_tabela")

    tabela = admin_dashboard._formatar_contagem_tabela({"barba": 1, "corte": 2})

    assert tabela == [
        {"Item": "corte", "Quantidade": 2},
        {"Item": "barba", "Quantidade": 1},
    ]


def test_admin_auth_login_correto_retorna_verdadeiro():
    from app.admin_auth import AdminCredentials, check_login

    credentials = AdminCredentials(username="admin", password="senha-forte", configured=True)

    assert check_login("admin", "senha-forte", credentials) is True


def test_admin_auth_senha_errada_retorna_falso():
    from app.admin_auth import AdminCredentials, check_login

    credentials = AdminCredentials(username="admin", password="senha-forte", configured=True)

    assert check_login("admin", "errada", credentials) is False


def test_admin_auth_usuario_errado_retorna_falso():
    from app.admin_auth import AdminCredentials, check_login

    credentials = AdminCredentials(username="admin", password="senha-forte", configured=True)

    assert check_login("outro", "senha-forte", credentials) is False


def test_admin_auth_nao_aceita_admin_admin_quando_env_nao_existe(monkeypatch):
    from app.admin_auth import check_login, get_admin_credentials

    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    credentials = get_admin_credentials()

    assert credentials.configured is False
    assert check_login("admin", "admin", credentials) is False


def test_admin_auth_env_incompleto_bloqueia_login(monkeypatch):
    from app.admin_auth import check_login, get_admin_credentials

    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    credentials = get_admin_credentials()

    assert credentials.configured is False
    assert check_login("admin", "admin", credentials) is False


def test_admin_auth_env_real_habilita_login(monkeypatch):
    from app.admin_auth import check_login, get_admin_credentials

    monkeypatch.setenv("ADMIN_USERNAME", "dono")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-forte")

    credentials = get_admin_credentials()

    assert credentials.configured is True
    assert check_login("dono", "senha-forte", credentials) is True
    assert check_login("admin", "admin", credentials) is False


def test_painel_sem_login_nao_carrega_dados_sensiveis(monkeypatch):
    import app.admin_dashboard as admin_dashboard

    fake_st = FakeStreamlit()

    def falhar_se_carregar_config():
        raise AssertionError("Painel nao deve carregar dados antes do login")

    monkeypatch.setattr(admin_dashboard, "st", fake_st)
    monkeypatch.setattr(admin_dashboard, "carregar_config", falhar_se_carregar_config)

    admin_dashboard.main()

    assert fake_st.dataframes == []


def test_painel_main_renderiza_com_streamlit_falso_sem_argumentos_incompativeis(tmp_path, monkeypatch):
    import app.admin_dashboard as admin_dashboard
    from app.admin_auth import SESSION_AUTH_KEY

    fake_st = FakeStreamlit()
    fake_st.session_state[SESSION_AUTH_KEY] = True
    monkeypatch.setenv("ADMIN_USERNAME", "dono")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-forte")
    agenda_repository = JsonAgendaRepository(tmp_path / "agenda.json")
    solicitacoes_repository = JsonAgendaRepository(tmp_path / "solicitacoes.json")
    agenda_repository.salvar([agendamento_base(data=date.today().isoformat())])
    solicitacoes_repository.salvar([])
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    monkeypatch.setattr(admin_dashboard, "st", fake_st)
    monkeypatch.setattr(admin_dashboard, "carregar_config", lambda: config)
    monkeypatch.setattr(admin_dashboard, "criar_agenda_repository", lambda _config=None: agenda_repository)
    monkeypatch.setattr(admin_dashboard, "JsonAgendaRepository", lambda _caminho=None: solicitacoes_repository)

    admin_dashboard.main()

    assert fake_st.dataframes
    assert all("hide_index" not in chamada for chamada in fake_st.dataframes)


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def metric(self, *args, **kwargs):
        pass


class FakeSidebar:
    def header(self, *args, **kwargs):
        pass

    def selectbox(self, _label, options, **_kwargs):
        return options[0] if options else None

    def date_input(self, _label, value=None, **_kwargs):
        return value

    def checkbox(self, *args, **kwargs):
        return False

    def button(self, *args, **kwargs):
        return False

    def info(self, *args, **kwargs):
        pass

    def markdown(self, *args, **kwargs):
        pass

    def subheader(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass


class FakeStreamlit:
    def __init__(self):
        self.sidebar = FakeSidebar()
        self.dataframes = []
        self.session_state = {}

    def set_page_config(self, *args, **kwargs):
        pass

    def title(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def text_input(self, *args, **kwargs):
        return ""

    def button(self, *args, **kwargs):
        return False

    def rerun(self):
        pass

    def tabs(self, nomes):
        return [FakeContext() for _nome in nomes]

    def columns(self, quantidade):
        return [FakeContext() for _indice in range(quantidade)]

    def subheader(self, *args, **kwargs):
        pass

    def text(self, *args, **kwargs):
        pass

    def markdown(self, *args, **kwargs):
        pass

    def write(self, *args, **kwargs):
        pass

    def code(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def dataframe(self, dados, **kwargs):
        if "hide_index" in kwargs:
            raise TypeError("hide_index não é aceito por este Streamlit falso")
        self.dataframes.append(kwargs)

