from collections import defaultdict
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from core.config.config_loader import carregar_config
from core.conversation.state import ConversationState
from core.scheduling.appointment_queries import (
    atualizar_status_agendamento,
    buscar_agendamentos_ativos_por_telefone,
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
        if normalizar_texto(mensagem) == "cancelar" and etapa not in {
            "escolha_inicial",
            "cancelamento_escolha",
            "cancelamento_confirmacao",
        }:
            self.encerrado = True
            self.state.etapa = "encerrado"
            return "Atendimento cancelado. Até mais!"

        if etapa == "escolha_inicial":
            return self._receber_escolha_inicial(mensagem)
        if etapa == "consulta_telefone":
            return self._receber_consulta_telefone(mensagem)
        if etapa == "cancelamento_telefone":
            return self._receber_cancelamento_telefone(mensagem)
        if etapa == "cancelamento_escolha":
            return self._receber_cancelamento_escolha(mensagem)
        if etapa == "cancelamento_confirmacao":
            return self._receber_cancelamento_confirmacao(mensagem)
        if etapa == "dia":
            return self._receber_dia(mensagem)
        if etapa == "servico":
            return self._receber_servico(mensagem)
        if etapa == "profissional":
            return self._receber_profissional(mensagem)
        if etapa == "periodo":
            return self._receber_periodo(mensagem)
        if etapa == "sem_disponibilidade":
            return self._receber_alternativa_sem_disponibilidade(mensagem)
        if etapa == "horario":
            return self._receber_horario(mensagem)
        if etapa == "nome":
            return self._receber_nome(mensagem)
        if etapa == "telefone":
            return self._receber_telefone(mensagem)
        if etapa == "confirmacao":
            return self._receber_confirmacao(mensagem)
        if etapa == "loja_categoria":
            return self._receber_categoria_loja(mensagem)
        if etapa == "loja_orcamento":
            return self._receber_orcamento_loja(mensagem)
        if etapa == "loja_nome":
            return self._receber_nome_loja(mensagem)

        self.encerrado = True
        return "Não consegui continuar o atendimento. Vamos encerrar por aqui."

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

        if not self.config.get("usa_agendamento") and self.config.get("modo") == "loja":
            if self._eh_opcao(resposta, "ver produtos"):
                self.state.etapa = "loja_categoria"
                return self._mensagem_categorias()
            if self._eh_opcao(resposta, "fazer orçamento"):
                self.state.etapa = "loja_orcamento"
                return self.mensagem("pergunta_orcamento")

        return f"Resposta inválida. Responda com: {self._opcoes_inicio_texto()}."

    def _receber_consulta_telefone(self, mensagem: str) -> str:
        telefone = validar_telefone(mensagem)
        if telefone is None:
            return f"Telefone inválido. {self.mensagem('consulta_pede_telefone')}"

        agendamentos = buscar_agendamentos_ativos_por_telefone(self.repository, telefone)
        self.encerrado = True
        self.state.etapa = "encerrado"

        if not agendamentos:
            return self.mensagem("agendamento_nao_encontrado")

        return "Encontrei estes agendamentos:\n\n" + self._formatar_lista_agendamentos(agendamentos)

    def _receber_cancelamento_telefone(self, mensagem: str) -> str:
        telefone = validar_telefone(mensagem)
        if telefone is None:
            return f"Telefone inválido. {self.mensagem('cancelamento_pede_telefone')}"

        agendamentos = buscar_agendamentos_ativos_por_telefone(self.repository, telefone)
        if not agendamentos:
            self.encerrado = True
            self.state.etapa = "encerrado"
            return self.mensagem("agendamento_nao_encontrado")

        self.state.telefone = telefone
        self.state.agendamentos_encontrados = agendamentos
        self.state.etapa = "cancelamento_escolha"
        return (
            "Encontrei estes agendamentos ativos:\n\n"
            f"{self._formatar_lista_agendamentos(agendamentos)}\n\n"
            "Digite o número do agendamento que deseja cancelar ou digite voltar."
        )

    def _receber_cancelamento_escolha(self, mensagem: str) -> str:
        resposta = normalizar_texto(mensagem)
        if resposta == "voltar":
            self.state = ConversationState(etapa="escolha_inicial")
            return self.iniciar()

        try:
            indice = int(mensagem.strip())
        except ValueError:
            return "Opção inválida. Digite o número do agendamento que deseja cancelar ou digite voltar."

        if indice < 1 or indice > len(self.state.agendamentos_encontrados):
            return "Opção inválida. Digite um número da lista ou digite voltar."

        self.state.agendamento_selecionado = self.state.agendamentos_encontrados[indice - 1]
        self.state.etapa = "cancelamento_confirmacao"
        resumo = self._formatar_agendamento(self.state.agendamento_selecionado)
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

        atualizado = atualizar_status_agendamento(
            self.repository,
            str(agendamento["id"]),
            "cancelado",
            {"cancelado_em": datetime.now().isoformat(timespec="seconds")},
        )
        self.encerrado = True
        self.state.etapa = "encerrado"

        if atualizado is None:
            return "Não consegui cancelar esse agendamento. Tente novamente mais tarde."
        return self.mensagem("cancelamento_confirmado")

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
        periodo = validar_periodo(mensagem, self.config)
        if periodo is not None:
            self.state.periodo = periodo
            return self._mostrar_horarios_ou_alternativas()

        data, erro = validar_data_agendamento(mensagem, hoje=self.hoje)
        if erro is None and data is not None:
            self.state.data = data
            self.state.periodo = None
            self.state.etapa = "periodo"
            return f"Certo, vamos tentar o dia {formatar_data_br(data)}. {self.mensagem('pergunta_periodo')}"
        if erro is not None and "anterior ao dia atual" in erro:
            return erro

        return (
            f"Não entendi. Digite outro período ({self._periodos_texto()}) ou outro dia "
            "(hoje, amanhã ou DD/MM/AAAA)."
        )

    def _mostrar_horarios_ou_alternativas(self) -> str:
        if self.state.data is None or self.state.servico is None or self.state.periodo is None:
            self.encerrado = True
            return "Faltaram dados para consultar a agenda. Vamos encerrar por aqui."

        agenda = self.repository.listar()
        opcoes = calcular_horarios_disponiveis(
            data=self.state.data,
            servico=self.state.servico,
            profissional_preferido=self.state.profissional_preferido,
            periodo=self.state.periodo,
            agenda=agenda,
            config=self.config,
        )

        if not opcoes:
            self.state.opcoes_horarios = []
            self.state.etapa = "sem_disponibilidade"
            return (
                "Não encontrei horários disponíveis para essa combinação. "
                f"Digite outro período ({self._periodos_texto()}) ou outro dia (hoje, amanhã ou DD/MM/AAAA)."
            )

        self.state.opcoes_horarios = opcoes
        self.state.etapa = "horario"
        return f"{self._formatar_opcoes_horarios(opcoes)}\n\nQual horário você quer?"

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
        return resposta_normalizada in {"alguem", "falar com alguem"} or any(
            "falar com" in normalizar_texto(item) and normalizar_texto(item) == resposta_normalizada
            for item in self.config.get("opcoes_inicio", [])
        )

    def _eh_opcao_agendar(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in {"agendar", "marcar"}

    def _eh_opcao_consultar(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in {"consultar", "ver agendamento"}

    def _eh_opcao_cancelar_agendamento(self, resposta_normalizada: str) -> bool:
        return resposta_normalizada in {"cancelar", "desmarcar"}

    def _validar_categoria(self, mensagem: str) -> str | None:
        valor = normalizar_texto(mensagem)
        for categoria in self.config.get("categorias", []):
            if normalizar_texto(categoria) == valor:
                return categoria
        return None

    def _formatar_lista_agendamentos(self, agendamentos: list[dict]) -> str:
        linhas = []
        for indice, agendamento in enumerate(agendamentos, start=1):
            linhas.append(f"{indice}. {self._formatar_agendamento(agendamento)}")
        return "\n".join(linhas)

    def _formatar_agendamento(self, agendamento: dict) -> str:
        servico = str(agendamento.get("servico", "")).capitalize()
        profissional = agendamento.get("profissional", "")
        data = formatar_data_br(str(agendamento.get("data", "")))
        horario = agendamento.get("horario", "")
        return f"{servico} com {profissional} em {data} às {horario}"
