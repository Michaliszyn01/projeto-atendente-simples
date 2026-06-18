from collections import defaultdict
from datetime import date
from typing import Any, Callable
from uuid import uuid4

from core.config.config_loader import carregar_config
from core.conversation.state import ConversationState
from core.scheduling.appointment_queries import (
    buscar_agendamentos_ativos_por_telefone,
    cancelar_agendamento,
    remarcar_agendamento,
)
from core.scheduling.availability import calcular_horarios_disponiveis
from core.scheduling.service import criar_agendamento
from core.scheduling.validators import (
    formatar_data_br,
    normalizar_horario,
    normalizar_texto,
    validar_data_agendamento,
    validar_periodo,
    validar_profissional,
    validar_resposta_sim_nao,
    validar_servico,
    validar_telefone,
)
from core.storage.json_repository import JsonAgendaRepository


OPCOES_AGENDAR = {"agendar", "marcar", "marcar horario"}
OPCOES_CONSULTAR = {"consultar", "ver agendamento", "meu horario", "qual meu horario"}
OPCOES_CANCELAR_AGENDAMENTO = {"cancelar", "desmarcar", "cancelar horario"}
OPCOES_REMARCAR = {"remarcar", "trocar horario", "mudar horario", "mudar agendamento"}
OPCOES_HUMANO = {"alguem", "falar com alguem", "atendente", "humano"}


class AtendimentoFlow:
    def __init__(
        self,
        repository: JsonAgendaRepository,
        hoje: date | None = None,
        config: dict[str, Any] | None = None,
        solicitacoes_repository: JsonAgendaRepository | None = None,
    ) -> None:
        self.repository = repository
        self.solicitacoes_repository = solicitacoes_repository
        self.config = config or carregar_config()
        self.hoje = hoje
        self.state = ConversationState()
        self.encerrado = False

    def iniciar(self) -> str:
        self.state = ConversationState(etapa="escolha_inicial")
        self.encerrado = False
        return self.mensagem("menu_inicial") or self.mensagem("inicio")

    def receber(self, mensagem: str) -> str:
        if self.encerrado:
            return "Atendimento já encerrado."

        etapa = self.state.etapa
        comando = normalizar_texto(mensagem)

        if comando == "sair":
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Atendimento encerrado. Até mais!"

        if comando == "menu":
            return self.iniciar()

        if comando == "voltar" and etapa not in {"escolha_inicial"}:
            return self._voltar()

        if comando == "cancelar" and etapa not in {
            "escolha_inicial",
            "cancelamento_escolha",
            "cancelamento_confirmacao",
        }:
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Atendimento cancelado. Até mais!"

        handler = self._handlers_por_etapa().get(etapa)
        if handler is not None:
            return handler(mensagem)

        self.encerrado = True
        return "Não consegui continuar o atendimento. Vamos encerrar por aqui."

    def _handlers_por_etapa(self) -> dict[str, Callable[[str], str]]:
        return {
            "escolha_inicial": self._receber_escolha_inicial,
            "consulta_telefone": self._receber_consulta_telefone,
            "cancelamento_telefone": self._receber_cancelamento_telefone,
            "cancelamento_escolha": self._receber_cancelamento_escolha,
            "cancelamento_confirmacao": self._receber_cancelamento_confirmacao,
            "remarcacao_telefone": self._receber_remarcacao_telefone,
            "remarcacao_escolha": self._receber_remarcacao_escolha,
            "remarcacao_dia": self._receber_remarcacao_dia,
            "remarcacao_periodo": self._receber_remarcacao_periodo,
            "remarcacao_sem_disponibilidade": self._receber_alternativa_remarcacao_sem_disponibilidade,
            "remarcacao_horario": self._receber_remarcacao_horario,
            "remarcacao_confirmacao": self._receber_remarcacao_confirmacao,
            "dia": self._receber_dia,
            "servico": self._receber_servico,
            "profissional": self._receber_profissional,
            "periodo": self._receber_periodo,
            "sem_disponibilidade": self._receber_alternativa_sem_disponibilidade,
            "horario": self._receber_horario,
            "nome": self._receber_nome,
            "telefone": self._receber_telefone,
            "confirmacao": self._receber_confirmacao,
            "loja_categoria": self._receber_categoria_loja,
            "loja_orcamento": self._receber_orcamento_loja,
            "loja_nome": self._receber_nome_loja,
        }

    def _receber_escolha_inicial(self, mensagem: str) -> str:
        resposta = normalizar_texto(mensagem)

        if self._eh_opcao_humano(resposta):
            self.encerrado = True
            self.state.etapa = "encerrado"
            return self.mensagem("humano")

        if self.config.get("usa_agendamento") and self._eh_opcao_agendar(resposta):
            self.state.etapa = "dia"
            return self.mensagem("pergunta_dia")

        if self.config.get("usa_agendamento") and self._eh_opcao_consultar(resposta):
            self.state.etapa = "consulta_telefone"
            return self.mensagem("consulta_pede_telefone")

        if self.config.get("usa_agendamento") and self._eh_opcao_cancelar_agendamento(resposta):
            self.state.etapa = "cancelamento_telefone"
            return self.mensagem("cancelamento_pede_telefone")

        if self.config.get("usa_agendamento") and self._eh_opcao_remarcar(resposta):
            self.state.etapa = "remarcacao_telefone"
            return self.mensagem("remarcacao_pede_telefone")

        if not self.config.get("usa_agendamento") and self.config.get("modo") == "loja":
            if self._eh_opcao_remarcar(resposta):
                return self.mensagem("remarcacao_indisponivel_loja") or (
                    "Remarcação de horário não está disponível para loja. "
                    f"{self.mensagem('humano')}"
                )
            if self._eh_opcao(resposta, "ver produtos"):
                self.state.etapa = "loja_categoria"
                return self._mensagem_categorias()
            if self._eh_opcao(resposta, "fazer orçamento"):
                self.state.etapa = "loja_orcamento"
                return self.mensagem("pergunta_orcamento")

        return f"Resposta inválida. Responda com: {self._opcoes_inicio_texto()}."

    def _receber_consulta_telefone(self, mensagem: str) -> str:
        agendamentos, erro = self._buscar_agendamentos_ativos_por_telefone(
            mensagem,
            "consulta_pede_telefone",
            "agendamento_nao_encontrado",
        )
        if erro is not None:
            return erro

        self.encerrado = True
        self.state.etapa = "encerrado"

        return "Encontrei estes agendamentos:\n\n" + self._formatar_lista_agendamentos(
            agendamentos,
            mostrar_remarcado=True,
        )

    def _receber_cancelamento_telefone(self, mensagem: str) -> str:
        agendamentos, erro = self._buscar_agendamentos_ativos_por_telefone(
            mensagem,
            "cancelamento_pede_telefone",
            "agendamento_nao_encontrado",
        )
        if erro is not None:
            return erro

        self.state.agendamentos_encontrados = agendamentos
        self.state.etapa = "cancelamento_escolha"
        return (
            "Encontrei estes agendamentos ativos:\n\n"
            f"{self._formatar_lista_agendamentos(agendamentos)}\n\n"
            "Digite o número do agendamento que deseja cancelar ou digite voltar."
        )

    def _receber_cancelamento_escolha(self, mensagem: str) -> str:
        agendamento, erro = self._selecionar_agendamento_da_lista(
            mensagem,
            "Opção inválida. Digite o número do agendamento que deseja cancelar ou digite voltar.",
        )
        if erro is not None:
            return erro

        self.state.agendamento_selecionado = agendamento
        self.state.etapa = "cancelamento_confirmacao"
        resumo = self._formatar_agendamento(agendamento)
        return f"{resumo}\n\n{self.mensagem('confirmacao_cancelamento')}"

    def _receber_cancelamento_confirmacao(self, mensagem: str) -> str:
        resposta = validar_resposta_sim_nao(mensagem)
        if resposta is None:
            return "Resposta inválida. Digite sim para confirmar ou não para manter o agendamento."

        if resposta == "nao":
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Cancelamento não realizado. O agendamento continua ativo."

        agendamento = self.state.agendamento_selecionado
        if not agendamento:
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Não consegui encontrar o agendamento selecionado. Vamos encerrar por aqui."

        atualizado = cancelar_agendamento(
            self.repository,
            str(agendamento["id"]),
        )
        self.encerrado = True
        self.state.etapa = "encerrado"

        if atualizado is None:
            return "Não consegui cancelar esse agendamento. Tente novamente mais tarde."
        return self.mensagem("cancelamento_confirmado")

    def _receber_remarcacao_telefone(self, mensagem: str) -> str:
        agendamentos, erro = self._buscar_agendamentos_ativos_por_telefone(
            mensagem,
            "remarcacao_pede_telefone",
            "remarcacao_nao_encontrado",
        )
        if erro is not None:
            return erro

        self.state.agendamentos_encontrados = agendamentos
        self.state.etapa = "remarcacao_escolha"
        return (
            "Encontrei estes agendamentos ativos:\n\n"
            f"{self._formatar_lista_agendamentos(agendamentos)}\n\n"
            f"{self.mensagem('remarcacao_escolha_agendamento')}"
        )

    def _receber_remarcacao_escolha(self, mensagem: str) -> str:
        agendamento, erro = self._selecionar_agendamento_da_lista(
            mensagem,
            self.mensagem("remarcacao_escolha_agendamento"),
        )
        if erro is not None:
            return erro

        self.state.agendamento_selecionado = agendamento
        self.state.servico = str(agendamento.get("servico"))
        self.state.profissional = str(agendamento.get("profissional"))
        self.state.profissional_preferido = self.state.profissional
        self.state.etapa = "remarcacao_dia"
        return self.mensagem("remarcacao_pergunta_dia")

    def _receber_remarcacao_dia(self, mensagem: str) -> str:
        data, erro = validar_data_agendamento(mensagem, hoje=self.hoje)

        if erro is not None:
            return erro

        self.state.nova_data = data
        self.state.etapa = "remarcacao_periodo"
        return self.mensagem("pergunta_periodo")

    def _receber_remarcacao_periodo(self, mensagem: str) -> str:
        periodo = validar_periodo(mensagem, self.config)

        if periodo is None:
            return f"Período inválido. Responda com {self._periodos_texto()}."

        self.state.novo_periodo = periodo
        return self._mostrar_horarios_remarcacao_ou_alternativas()

    def _receber_alternativa_remarcacao_sem_disponibilidade(self, mensagem: str) -> str:
        return self._receber_periodo_ou_data_alternativa(
            mensagem=mensagem,
            atributo_data="nova_data",
            atributo_periodo="novo_periodo",
            etapa_periodo="remarcacao_periodo",
            mostrar_horarios=self._mostrar_horarios_remarcacao_ou_alternativas,
        )

    def _mostrar_horarios_remarcacao_ou_alternativas(self) -> str:
        agendamento = self.state.agendamento_selecionado
        if (
            agendamento is None
            or self.state.nova_data is None
            or self.state.servico is None
            or self.state.novo_periodo is None
            or self.state.profissional is None
        ):
            self.encerrado = True
            return "Faltaram dados para consultar a agenda. Vamos encerrar por aqui."

        return self._mostrar_horarios_ou_mensagem(
            data=self.state.nova_data,
            servico=self.state.servico,
            profissional_preferido=self.state.profissional,
            periodo=self.state.novo_periodo,
            ignorar_agendamento_id=str(agendamento["id"]),
            etapa_horario="remarcacao_horario",
            etapa_sem_disponibilidade="remarcacao_sem_disponibilidade",
            mensagem_sem_disponibilidade=self.mensagem("remarcacao_sem_horarios"),
            pergunta_horario="Qual novo horário você quer?",
        )

    def _receber_remarcacao_horario(self, mensagem: str) -> str:
        horario = normalizar_horario(mensagem)

        if horario is None:
            return "Horário inválido. Digite um horário como 10, 10:00, 15 ou 15:00."

        profissional = self._escolher_profissional_para_horario(horario)
        if profissional is None:
            return "Esse horário não está disponível na lista. Escolha um dos horários mostrados."

        self.state.novo_horario = horario
        self.state.profissional = profissional
        self.state.etapa = "remarcacao_confirmacao"
        return self._montar_confirmacao_remarcacao()

    def _receber_remarcacao_confirmacao(self, mensagem: str) -> str:
        resposta = validar_resposta_sim_nao(mensagem)

        if resposta == "nao":
            self.encerrado = True
            self.state.etapa = "encerrado"
            return self.mensagem("remarcacao_cancelada")

        if resposta != "sim":
            return "Resposta inválida. Digite sim para confirmar ou não para cancelar."

        agendamento = self.state.agendamento_selecionado
        if agendamento is None or self.state.nova_data is None or self.state.novo_horario is None or self.state.profissional is None:
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Faltaram dados para remarcar. Vamos encerrar por aqui."

        atualizado = remarcar_agendamento(
            self.repository,
            str(agendamento["id"]),
            self.state.nova_data,
            self.state.novo_horario,
            self.state.profissional,
        )

        self.encerrado = True
        self.state.etapa = "encerrado"
        if atualizado is None:
            return "Não consegui remarcar esse agendamento. Tente novamente mais tarde."
        return self.mensagem("remarcacao_concluida")

    def _receber_dia(self, mensagem: str) -> str:
        data, erro = validar_data_agendamento(mensagem, hoje=self.hoje)

        if erro is not None:
            return erro

        self.state.data = data
        self.state.etapa = "servico"
        return self._pergunta_servico()

    def _receber_servico(self, mensagem: str) -> str:
        servico = validar_servico(mensagem, self.config)

        if servico is None:
            return f"{self.rotulo_servico().capitalize()} inválido. Opções: {self._servicos_texto()}."

        self.state.servico = servico
        self.state.etapa = "profissional"
        return self._pergunta_profissional()

    def _receber_profissional(self, mensagem: str) -> str:
        valido, profissional = validar_profissional(mensagem, self.config)

        if not valido:
            return f"{self.rotulo_profissional().capitalize()} inválido. Opções: {self._profissionais_texto()} ou não."

        self.state.profissional_preferido = profissional
        self.state.etapa = "periodo"
        return self.mensagem("pergunta_periodo")

    def _receber_periodo(self, mensagem: str) -> str:
        periodo = validar_periodo(mensagem, self.config)

        if periodo is None:
            return f"Período inválido. Responda com {self._periodos_texto()}."

        self.state.periodo = periodo
        return self._mostrar_horarios_ou_alternativas()

    def _receber_alternativa_sem_disponibilidade(self, mensagem: str) -> str:
        return self._receber_periodo_ou_data_alternativa(
            mensagem=mensagem,
            atributo_data="data",
            atributo_periodo="periodo",
            etapa_periodo="periodo",
            mostrar_horarios=self._mostrar_horarios_ou_alternativas,
        )

    def _mostrar_horarios_ou_alternativas(self) -> str:
        if self.state.data is None or self.state.servico is None or self.state.periodo is None:
            self.encerrado = True
            return "Faltaram dados para consultar a agenda. Vamos encerrar por aqui."

        return self._mostrar_horarios_ou_mensagem(
            data=self.state.data,
            servico=self.state.servico,
            profissional_preferido=self.state.profissional_preferido,
            periodo=self.state.periodo,
            ignorar_agendamento_id=None,
            etapa_horario="horario",
            etapa_sem_disponibilidade="sem_disponibilidade",
            mensagem_sem_disponibilidade="Não encontrei horários disponíveis para essa combinação.",
            pergunta_horario="Qual horário você quer?",
        )

    def _receber_horario(self, mensagem: str) -> str:
        horario = normalizar_horario(mensagem)

        if horario is None:
            return "Horário inválido. Digite um horário como 10, 10:00, 15 ou 15:00."

        profissional = self._escolher_profissional_para_horario(horario)

        if profissional is None:
            return "Esse horário não está disponível na lista. Escolha um dos horários mostrados."

        self.state.horario = horario
        self.state.profissional = profissional
        self.state.etapa = "nome"
        return self.mensagem("pergunta_nome")

    def _receber_nome(self, mensagem: str) -> str:
        nome = mensagem.strip()

        if len(nome) < 2:
            return f"Nome inválido. {self.mensagem('pergunta_nome')}"

        self.state.nome = nome
        self.state.etapa = "telefone"
        return self.mensagem("pergunta_telefone")

    def _receber_telefone(self, mensagem: str) -> str:
        telefone = validar_telefone(mensagem)

        if telefone is None:
            return f"Telefone inválido. {self.mensagem('pergunta_telefone')}"

        self.state.telefone = telefone
        self.state.etapa = "confirmacao"
        return self._montar_confirmacao()

    def _receber_confirmacao(self, mensagem: str) -> str:
        resposta = validar_resposta_sim_nao(mensagem)

        if resposta == "nao":
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Agendamento cancelado. Até mais!"

        if resposta != "sim":
            return "Resposta inválida. Digite sim para confirmar ou não para cancelar."

        try:
            agendamento = criar_agendamento(self.state, self.repository, self.config)
        except ValueError as exc:
            self.state.etapa = "periodo"
            self.state.horario = None
            self.state.profissional = None
            return f"{exc} {self.mensagem('pergunta_periodo')}"

        self.encerrado = True
        self.state.etapa = "encerrado"
        return (
            "Agendamento confirmado! Um atendente te espera no dia "
            f"{formatar_data_br(agendamento['data'])} às {agendamento['horario']} "
            f"com {agendamento['profissional']}."
        )

    def _receber_categoria_loja(self, mensagem: str) -> str:
        categoria = self._validar_categoria(mensagem)
        if categoria is None:
            return f"Categoria inválida. Categorias disponíveis: {self._categorias_texto()}."

        self.state.categoria = categoria
        self.encerrado = True
        self.state.etapa = "encerrado"
        return f"Temos produtos na categoria {categoria}. {self.mensagem('humano')}"

    def _receber_orcamento_loja(self, mensagem: str) -> str:
        descricao = mensagem.strip()
        if len(descricao) < 3:
            return self.mensagem("pergunta_orcamento")

        self.state.descricao_orcamento = descricao
        self.state.etapa = "loja_nome"
        return self.mensagem("pergunta_nome")

    def _receber_nome_loja(self, mensagem: str) -> str:
        nome = mensagem.strip()
        if len(nome) < 2:
            return f"Nome inválido. {self.mensagem('pergunta_nome')}"

        self.state.nome = nome
        solicitacao = {
            "id": str(uuid4()),
            "nome": self.state.nome,
            "descricao": self.state.descricao_orcamento,
            "status": "registrado",
        }
        repository = self.solicitacoes_repository or JsonAgendaRepository("data/solicitacoes.json")
        repository.adicionar(solicitacao)
        self.encerrado = True
        self.state.etapa = "encerrado"
        return "Solicitação registrada. Vou chamar alguém para continuar o atendimento."

    def _buscar_agendamentos_ativos_por_telefone(
        self,
        mensagem: str,
        chave_pergunta_telefone: str,
        chave_nao_encontrado: str,
    ) -> tuple[list[dict], str | None]:
        telefone = validar_telefone(mensagem)
        if telefone is None:
            return [], f"Telefone inválido. {self.mensagem(chave_pergunta_telefone)}"

        agendamentos = buscar_agendamentos_ativos_por_telefone(self.repository, telefone)
        if not agendamentos:
            self.encerrado = True
            self.state.etapa = "encerrado"
            return [], self.mensagem(chave_nao_encontrado) or self.mensagem("agendamento_nao_encontrado")

        self.state.telefone = telefone
        return agendamentos, None

    def _selecionar_agendamento_da_lista(
        self,
        mensagem: str,
        mensagem_invalida: str,
    ) -> tuple[dict | None, str | None]:
        if normalizar_texto(mensagem) == "voltar":
            self.state = ConversationState(etapa="escolha_inicial")
            return None, self.iniciar()

        try:
            indice = int(mensagem.strip())
        except ValueError:
            return None, mensagem_invalida

        if indice < 1 or indice > len(self.state.agendamentos_encontrados):
            return None, "Opção inválida. Digite um número da lista ou digite voltar."

        return self.state.agendamentos_encontrados[indice - 1], None

    def _receber_periodo_ou_data_alternativa(
        self,
        mensagem: str,
        atributo_data: str,
        atributo_periodo: str,
        etapa_periodo: str,
        mostrar_horarios: Callable[[], str],
    ) -> str:
        periodo = validar_periodo(mensagem, self.config)
        if periodo is not None:
            setattr(self.state, atributo_periodo, periodo)
            return mostrar_horarios()

        data, erro = validar_data_agendamento(mensagem, hoje=self.hoje)
        if erro is None and data is not None:
            setattr(self.state, atributo_data, data)
            setattr(self.state, atributo_periodo, None)
            self.state.etapa = etapa_periodo
            return f"Certo, vamos tentar o dia {formatar_data_br(data)}. {self.mensagem('pergunta_periodo')}"
        if erro is not None and "anterior ao dia atual" in erro:
            return erro

        return (
            f"Não entendi. Digite outro período ({self._periodos_texto()}) ou outro dia "
            "(hoje, amanhã ou DD/MM/AAAA)."
        )

    def _mostrar_horarios_ou_mensagem(
        self,
        data: str,
        servico: str,
        profissional_preferido: str | None,
        periodo: str,
        ignorar_agendamento_id: str | None,
        etapa_horario: str,
        etapa_sem_disponibilidade: str,
        mensagem_sem_disponibilidade: str,
        pergunta_horario: str,
    ) -> str:
        opcoes = calcular_horarios_disponiveis(
            data=data,
            servico=servico,
            profissional_preferido=profissional_preferido,
            periodo=periodo,
            agenda=self.repository.listar(),
            config=self.config,
            ignorar_agendamento_id=ignorar_agendamento_id,
        )

        if not opcoes:
            self.state.opcoes_horarios = []
            self.state.etapa = etapa_sem_disponibilidade
            return (
                f"{mensagem_sem_disponibilidade} "
                f"Digite outro período ({self._periodos_texto()}) ou outro dia (hoje, amanhã ou DD/MM/AAAA)."
            )

        self.state.opcoes_horarios = opcoes
        self.state.etapa = etapa_horario
        return f"{self._formatar_opcoes_horarios(opcoes)}\n\n{pergunta_horario}"

    def _formatar_opcoes_horarios(self, opcoes: list[dict[str, str]]) -> str:
        por_horario: dict[str, list[str]] = {}

        for opcao in opcoes:
            por_horario.setdefault(opcao["horario"], []).append(opcao["profissional"])

        linhas = ["Horários disponíveis:"]
        for horario, profissionais in por_horario.items():
            if self.state.profissional_preferido is None:
                linhas.append(f"- {horario} ({' ou '.join(profissionais)})")
            else:
                linhas.append(f"- {horario}")

        return "\n".join(linhas)

    def _escolher_profissional_para_horario(self, horario: str) -> str | None:
        for opcao in self.state.opcoes_horarios:
            if opcao["horario"] == horario:
                return opcao["profissional"]
        return None

    def _montar_confirmacao(self) -> str:
        return (
            f"Nome: {self.state.nome}\n"
            f"{self.rotulo_servico().capitalize()}: {self.state.servico}\n"
            f"Telefone: {self.state.telefone}\n"
            f"Dia: {formatar_data_br(self.state.data or '')}\n"
            f"Horário: {self.state.horario}\n"
            f"{self.rotulo_profissional().capitalize()}: {self.state.profissional}\n\n"
            "Digite sim para confirmar ou não para cancelar."
        )

    def _montar_confirmacao_remarcacao(self) -> str:
        agendamento = self.state.agendamento_selecionado or {}
        novo = {
            "servico": agendamento.get("servico", ""),
            "profissional": self.state.profissional,
            "data": self.state.nova_data,
            "horario": self.state.novo_horario,
        }
        return (
            "Confirmando remarcação:\n"
            "Agendamento atual:\n"
            f"{self._formatar_agendamento(agendamento)}\n\n"
            "Novo agendamento:\n"
            f"{self._formatar_agendamento(novo)}\n\n"
            f"{self.mensagem('confirmacao_remarcacao')}"
        )

    def _pergunta_servico(self) -> str:
        return f"{self.mensagem('pergunta_servico')} Opções: {self._servicos_texto()}."

    def _pergunta_profissional(self) -> str:
        return f"{self.mensagem('pergunta_profissional')} Opções: {self._profissionais_texto()} ou não."

    def _mensagem_categorias(self) -> str:
        return f"{self.mensagem('pergunta_categoria')} Categorias disponíveis: {self._categorias_texto()}."

    def mensagem(self, chave: str) -> str:
        valor = str(self.config.get("mensagens", {}).get(chave, ""))
        contexto = defaultdict(str, self.config)
        return valor.format_map(contexto)

    def rotulo_profissional(self) -> str:
        return str(self.config.get("nome_profissional", "profissional"))

    def rotulo_servico(self) -> str:
        return str(self.config.get("nome_servico", "serviço"))

    def _servicos_texto(self) -> str:
        return ", ".join(self.config.get("servicos", {}).keys())

    def _profissionais_texto(self) -> str:
        return ", ".join(self.config.get("profissionais", []))

    def _periodos_texto(self) -> str:
        return " ou ".join(self.config.get("horarios", {}).keys())

    def _categorias_texto(self) -> str:
        return ", ".join(self.config.get("categorias", []))

    def _opcoes_inicio_texto(self) -> str:
        return " ou ".join(self.config.get("opcoes_inicio", []))

    def _eh_opcao(self, resposta_normalizada: str, opcao: str) -> bool:
        return any(normalizar_texto(item) == resposta_normalizada for item in self.config.get("opcoes_inicio", [])) and (
            normalizar_texto(opcao) == resposta_normalizada
        )

    def _eh_opcao_humano(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in OPCOES_HUMANO or any(
            "falar com" in normalizar_texto(item) and normalizar_texto(item) == resposta_normalizada
            for item in self.config.get("opcoes_inicio", [])
        )

    def _eh_opcao_agendar(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in OPCOES_AGENDAR

    def _eh_opcao_consultar(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in OPCOES_CONSULTAR

    def _eh_opcao_cancelar_agendamento(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in OPCOES_CANCELAR_AGENDAMENTO

    def _eh_opcao_remarcar(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in OPCOES_REMARCAR

    def _validar_categoria(self, mensagem: str) -> str | None:
        valor = normalizar_texto(mensagem)
        for categoria in self.config.get("categorias", []):
            if normalizar_texto(categoria) == valor:
                return categoria
        return None

    def _formatar_lista_agendamentos(self, agendamentos: list[dict], mostrar_remarcado: bool = False) -> str:
        linhas = []
        for indice, agendamento in enumerate(agendamentos, start=1):
            linha = f"{indice}. {self._formatar_agendamento(agendamento)}"
            if mostrar_remarcado and agendamento.get("remarcado_em"):
                linha += "\nEste agendamento já foi remarcado anteriormente."
            linhas.append(linha)
        return "\n".join(linhas)

    def _formatar_agendamento(self, agendamento: dict) -> str:
        servico = str(agendamento.get("servico", "")).capitalize()
        profissional = agendamento.get("profissional", "")
        data = formatar_data_br(str(agendamento.get("data", "")))
        horario = agendamento.get("horario", "")
        return f"{servico} com {profissional} em {data} às {horario}"

    def _voltar(self) -> str:
        etapa = self.state.etapa

        if etapa in {"consulta_telefone", "cancelamento_telefone", "remarcacao_telefone"}:
            return self.iniciar()
        if etapa in {"cancelamento_escolha", "remarcacao_escolha"}:
            self.state.etapa = "escolha_inicial"
            return self.iniciar()
        if etapa == "cancelamento_confirmacao":
            self.state.etapa = "cancelamento_escolha"
            return (
                "Encontrei estes agendamentos ativos:\n\n"
                f"{self._formatar_lista_agendamentos(self.state.agendamentos_encontrados)}\n\n"
                "Digite o número do agendamento que deseja cancelar ou digite voltar."
            )
        if etapa == "remarcacao_dia":
            self.state.etapa = "remarcacao_escolha"
            return self.mensagem("remarcacao_escolha_agendamento")
        if etapa in {"remarcacao_periodo", "remarcacao_sem_disponibilidade"}:
            self.state.etapa = "remarcacao_dia"
            return self.mensagem("remarcacao_pergunta_dia")
        if etapa == "remarcacao_horario":
            self.state.etapa = "remarcacao_periodo"
            return self.mensagem("pergunta_periodo")
        if etapa == "remarcacao_confirmacao":
            self.state.etapa = "remarcacao_horario"
            return f"{self._formatar_opcoes_horarios(self.state.opcoes_horarios)}\n\nQual novo horário você quer?"
        if etapa == "servico":
            self.state.etapa = "dia"
            return self.mensagem("pergunta_dia")
        if etapa == "profissional":
            self.state.etapa = "servico"
            return self._pergunta_servico()
        if etapa == "periodo":
            self.state.etapa = "profissional"
            return self._pergunta_profissional()
        if etapa in {"horario", "sem_disponibilidade"}:
            self.state.etapa = "periodo"
            return self.mensagem("pergunta_periodo")
        if etapa == "nome":
            self.state.etapa = "horario"
            return f"{self._formatar_opcoes_horarios(self.state.opcoes_horarios)}\n\nQual horário você quer?"
        if etapa == "telefone":
            self.state.etapa = "nome"
            return self.mensagem("pergunta_nome")
        if etapa == "confirmacao":
            self.state.etapa = "telefone"
            return self.mensagem("pergunta_telefone")
        if etapa == "loja_orcamento":
            return self.iniciar()
        if etapa == "loja_nome":
            self.state.etapa = "loja_orcamento"
            return self.mensagem("pergunta_orcamento")

        return self.iniciar()
