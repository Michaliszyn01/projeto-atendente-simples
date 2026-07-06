import json
import sqlite3
import threading
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.conversation.state import ConversationState
from core.scheduling.validators import normalizar_telefone_whatsapp


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "agenda.db"
_LOCKS_POR_DB: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

AGENDAMENTO_COLUNAS = {
    "id",
    "cliente_id",
    "telefone",
    "telefone_normalizado",
    "nome",
    "servico",
    "profissional",
    "data",
    "horario",
    "duracao_minutos",
    "status",
    "criado_em",
    "atualizado_em",
    "cancelado_em",
    "remarcado_em",
    "remarcado_de_id",
    "observacoes",
    "origem",
    "payload_json",
}


class SQLiteAgendaRepository:
    def __init__(self, caminho: str | Path | None = None) -> None:
        self.caminho = Path(caminho) if caminho is not None else DEFAULT_DB_PATH
        if not self.caminho.is_absolute():
            self.caminho = PROJECT_ROOT / self.caminho
        self.caminho = self.caminho.resolve()
        self._lock = _lock_para_db(self.caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar_schema()

    def listar(self) -> list[dict]:
        with self._conectar() as conn:
            linhas = conn.execute(
                "SELECT * FROM agendamentos ORDER BY data, horario, profissional, nome"
            ).fetchall()
        return [self._linha_para_agendamento(linha) for linha in linhas]

    def salvar(self, agenda: list[dict]) -> None:
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    conn.execute("DELETE FROM agendamentos")
                    for agendamento in agenda:
                        self._inserir_ou_substituir(conn, agendamento)

    def adicionar(self, agendamento: dict) -> None:
        self.adicionar_agendamento(agendamento)

    def adicionar_agendamento(self, agendamento: dict) -> None:
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    self._inserir_ou_substituir(conn, agendamento)

    def buscar_agendamentos_por_telefone(
        self,
        telefone: str,
        apenas_ativos: bool = True,
    ) -> list[dict]:
        telefone_normalizado = _normalizar_telefone_ou_valor(telefone)
        sql = "SELECT * FROM agendamentos WHERE telefone_normalizado = ?"
        params: list[Any] = [telefone_normalizado]
        if apenas_ativos:
            sql += " AND status != ?"
            params.append("cancelado")
        sql += " ORDER BY data, horario, profissional, nome"

        with self._conectar() as conn:
            linhas = conn.execute(sql, params).fetchall()
        return [self._linha_para_agendamento(linha) for linha in linhas]

    def buscar_agendamentos_ativos_por_telefone(self, telefone: str) -> list[dict]:
        return self.buscar_agendamentos_por_telefone(telefone, apenas_ativos=True)

    def buscar_agendamento_por_id(self, agendamento_id: str) -> dict | None:
        with self._conectar() as conn:
            linha = conn.execute(
                "SELECT * FROM agendamentos WHERE id = ?",
                (agendamento_id,),
            ).fetchone()
        if linha is None:
            return None
        return self._linha_para_agendamento(linha)

    def atualizar_agendamento(self, agendamento_id: str, dados_atualizados: dict) -> dict | None:
        agendamento = self.buscar_agendamento_por_id(agendamento_id)
        if agendamento is None:
            return None

        atualizado = {**agendamento, **dados_atualizados, "atualizado_em": self._agora()}
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    self._inserir_ou_substituir(conn, atualizado)
        return self.buscar_agendamento_por_id(agendamento_id)

    def cancelar_agendamento(self, agendamento_id: str) -> dict | None:
        feito_em = self._agora()
        agendamento = self.buscar_agendamento_por_id(agendamento_id)
        if agendamento is None:
            return None
        if agendamento.get("status") == "cancelado":
            return agendamento

        return self.atualizar_agendamento(
            agendamento_id,
            {
                "status": "cancelado",
                "cancelado_em": feito_em,
                "historico": self._historico_com_evento(
                    agendamento,
                    {"acao": "cancelado", "feito_em": feito_em},
                ),
            },
        )

    def remarcar_agendamento(
        self,
        agendamento_id: str,
        nova_data: str,
        novo_horario: str,
        profissional: str,
    ) -> dict | None:
        feito_em = self._agora()
        agendamento = self.buscar_agendamento_por_id(agendamento_id)
        if agendamento is None:
            return None
        if (
            agendamento.get("status") != "cancelado"
            and agendamento.get("data") == nova_data
            and agendamento.get("horario") == novo_horario
            and agendamento.get("profissional") == profissional
        ):
            return agendamento

        evento = {
            "acao": "remarcado",
            "data_anterior": agendamento.get("data"),
            "horario_anterior": agendamento.get("horario"),
            "profissional_anterior": agendamento.get("profissional"),
            "data_nova": nova_data,
            "horario_novo": novo_horario,
            "profissional_novo": profissional,
            "feito_em": feito_em,
        }

        return self.atualizar_agendamento(
            agendamento_id,
            {
                "data": nova_data,
                "horario": novo_horario,
                "profissional": profissional,
                "status": "agendado",
                "remarcado_em": feito_em,
                "historico": self._historico_com_evento(agendamento, evento),
            },
        )

    def limpar(self) -> None:
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    conn.execute("DELETE FROM agendamentos")

    def upsert_cliente(
        self,
        telefone: str,
        nome: str | None = None,
        whatsapp_raw_id: str | None = None,
        payload: dict | None = None,
    ) -> str:
        telefone_normalizado = _normalizar_telefone_ou_valor(telefone)
        agora = self._agora()
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    self._upsert_cliente(
                        conn,
                        telefone=telefone,
                        telefone_normalizado=telefone_normalizado,
                        nome=nome,
                        whatsapp_raw_id=whatsapp_raw_id,
                        payload=payload,
                        agora=agora,
                    )
        return telefone_normalizado

    def listar_solicitacoes_humano(self) -> list[dict]:
        with self._conectar() as conn:
            linhas = conn.execute(
                """
                SELECT
                    sessions.client_id,
                    sessions.telefone_normalizado,
                    sessions.state_json,
                    sessions.etapa_atual,
                    sessions.atualizado_em,
                    clientes.telefone,
                    clientes.whatsapp_raw_id,
                    clientes.nome AS nome_cliente
                FROM sessions
                LEFT JOIN clientes ON clientes.id = sessions.client_id
                ORDER BY sessions.atualizado_em DESC
                """
            ).fetchall()

        solicitacoes = []
        for linha in linhas:
            solicitacao = self._linha_para_solicitacao_humano(linha)
            if solicitacao is not None:
                solicitacoes.append(solicitacao)
        return solicitacoes

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.caminho, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _inicializar_schema(self) -> None:
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS clientes (
                            id TEXT PRIMARY KEY,
                            telefone TEXT NOT NULL UNIQUE,
                            telefone_normalizado TEXT NOT NULL UNIQUE,
                            whatsapp_raw_id TEXT,
                            nome TEXT,
                            criado_em TEXT NOT NULL,
                            atualizado_em TEXT NOT NULL,
                            ultimo_contato_em TEXT,
                            payload_json TEXT
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            client_id TEXT PRIMARY KEY,
                            telefone_normalizado TEXT NOT NULL,
                            state_json TEXT NOT NULL,
                            etapa_atual TEXT,
                            atualizado_em TEXT NOT NULL,
                            expires_at TEXT,
                            FOREIGN KEY (client_id) REFERENCES clientes(id)
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agendamentos (
                            id TEXT PRIMARY KEY,
                            cliente_id TEXT,
                            telefone TEXT NOT NULL,
                            telefone_normalizado TEXT NOT NULL,
                            nome TEXT,
                            servico TEXT NOT NULL,
                            profissional TEXT,
                            data TEXT NOT NULL,
                            horario TEXT NOT NULL,
                            duracao_minutos INTEGER,
                            status TEXT NOT NULL,
                            criado_em TEXT NOT NULL,
                            atualizado_em TEXT NOT NULL,
                            cancelado_em TEXT,
                            remarcado_em TEXT,
                            remarcado_de_id TEXT,
                            observacoes TEXT,
                            origem TEXT DEFAULT 'whatsapp',
                            payload_json TEXT,
                            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
                        )
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_agendamentos_telefone ON agendamentos(telefone_normalizado)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_agendamentos_data ON agendamentos(data, horario)"
                    )
                    conn.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_agendamentos_horario_ativo
                        ON agendamentos(data, horario, COALESCE(profissional, ''))
                        WHERE status != 'cancelado'
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS mensagens (
                            id TEXT PRIMARY KEY,
                            client_id TEXT NOT NULL,
                            telefone_normalizado TEXT NOT NULL,
                            direcao TEXT NOT NULL,
                            mensagem TEXT NOT NULL,
                            criado_em TEXT NOT NULL,
                            canal TEXT DEFAULT 'whatsapp',
                            message_id_externo TEXT,
                            payload_json TEXT,
                            FOREIGN KEY (client_id) REFERENCES clientes(id)
                        )
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_mensagens_message_id_externo ON mensagens(message_id_externo)"
                    )
                    conn.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_mensagens_message_id_externo_unico
                        ON mensagens(message_id_externo)
                        WHERE message_id_externo IS NOT NULL
                        """
                    )

    def mensagem_externa_processada(self, message_id_externo: str) -> bool:
        if not message_id_externo:
            return False
        with self._conectar() as conn:
            linha = conn.execute(
                "SELECT 1 FROM mensagens WHERE message_id_externo = ? LIMIT 1",
                (message_id_externo,),
            ).fetchone()
        return linha is not None

    def registrar_mensagem(
        self,
        telefone: str,
        direcao: str,
        mensagem: str,
        canal: str = "whatsapp",
        message_id_externo: str | None = None,
        payload: dict | None = None,
    ) -> None:
        telefone_normalizado = _normalizar_telefone_ou_valor(telefone)
        agora = self._agora()
        with self._lock:
            with self._conectar() as conn:
                with conn:
                    self._upsert_cliente(
                        conn,
                        telefone=telefone,
                        telefone_normalizado=telefone_normalizado,
                        nome=None,
                        whatsapp_raw_id=telefone,
                        payload=None,
                        agora=agora,
                    )
                    conn.execute(
                        """
                        INSERT INTO mensagens (
                            id, client_id, telefone_normalizado, direcao, mensagem,
                            criado_em, canal, message_id_externo, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            telefone_normalizado,
                            telefone_normalizado,
                            direcao,
                            mensagem,
                            agora,
                            canal,
                            message_id_externo,
                            json.dumps(payload, ensure_ascii=False) if payload else None,
                        ),
                    )

    def registrar_mensagem_unica(
        self,
        telefone: str,
        direcao: str,
        mensagem: str,
        canal: str,
        message_id_externo: str,
        payload: dict | None = None,
    ) -> bool:
        try:
            self.registrar_mensagem(
                telefone=telefone,
                direcao=direcao,
                mensagem=mensagem,
                canal=canal,
                message_id_externo=message_id_externo,
                payload=payload,
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def _inserir_ou_substituir(self, conn: sqlite3.Connection, agendamento: dict) -> None:
        dados = dict(agendamento)
        agora = self._agora()
        dados.setdefault("id", str(uuid4()))
        dados.setdefault("servico", "")
        dados.setdefault("data", "")
        dados.setdefault("horario", "")
        dados.setdefault("status", "agendado")
        dados.setdefault("criado_em", agora)
        dados.setdefault("atualizado_em", dados.get("criado_em") or agora)
        dados.setdefault("origem", "whatsapp")
        telefone = str(dados.get("telefone") or dados.get("telefone_normalizado") or "")
        telefone_normalizado = _normalizar_telefone_ou_valor(telefone)
        dados["telefone"] = telefone or telefone_normalizado
        dados["telefone_normalizado"] = telefone_normalizado
        dados["cliente_id"] = telefone_normalizado

        self._upsert_cliente(
            conn,
            telefone=dados["telefone"],
            telefone_normalizado=telefone_normalizado,
            nome=dados.get("nome"),
            whatsapp_raw_id=dados.get("whatsapp_raw_id"),
            payload=None,
            agora=agora,
        )

        payload = self._montar_payload_agendamento(dados)
        valores = {coluna: dados.get(coluna) for coluna in AGENDAMENTO_COLUNAS}
        valores["payload_json"] = json.dumps(payload, ensure_ascii=False) if payload else None

        try:
            conn.execute(
                """
                INSERT INTO agendamentos (
                    id, cliente_id, telefone, telefone_normalizado, nome, servico,
                    profissional, data, horario, duracao_minutos, status, criado_em,
                    atualizado_em, cancelado_em, remarcado_em, remarcado_de_id,
                    observacoes, origem, payload_json
                ) VALUES (
                    :id, :cliente_id, :telefone, :telefone_normalizado, :nome, :servico,
                    :profissional, :data, :horario, :duracao_minutos, :status, :criado_em,
                    :atualizado_em, :cancelado_em, :remarcado_em, :remarcado_de_id,
                    :observacoes, :origem, :payload_json
                )
                ON CONFLICT(id) DO UPDATE SET
                    cliente_id = excluded.cliente_id,
                    telefone = excluded.telefone,
                    telefone_normalizado = excluded.telefone_normalizado,
                    nome = excluded.nome,
                    servico = excluded.servico,
                    profissional = excluded.profissional,
                    data = excluded.data,
                    horario = excluded.horario,
                    duracao_minutos = excluded.duracao_minutos,
                    status = excluded.status,
                    criado_em = excluded.criado_em,
                    atualizado_em = excluded.atualizado_em,
                    cancelado_em = excluded.cancelado_em,
                    remarcado_em = excluded.remarcado_em,
                    remarcado_de_id = excluded.remarcado_de_id,
                    observacoes = excluded.observacoes,
                    origem = excluded.origem,
                    payload_json = excluded.payload_json
                """,
                valores,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Esse horário acabou de ser ocupado. Escolha outro horário disponível.") from exc

    def _upsert_cliente(
        self,
        conn: sqlite3.Connection,
        telefone: str,
        telefone_normalizado: str,
        nome: str | None,
        whatsapp_raw_id: str | None,
        payload: dict | None,
        agora: str,
    ) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
        conn.execute(
            """
            INSERT INTO clientes (
                id, telefone, telefone_normalizado, whatsapp_raw_id, nome,
                criado_em, atualizado_em, ultimo_contato_em, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                telefone = excluded.telefone,
                telefone_normalizado = excluded.telefone_normalizado,
                whatsapp_raw_id = COALESCE(excluded.whatsapp_raw_id, clientes.whatsapp_raw_id),
                nome = COALESCE(excluded.nome, clientes.nome),
                atualizado_em = excluded.atualizado_em,
                ultimo_contato_em = excluded.ultimo_contato_em,
                payload_json = COALESCE(excluded.payload_json, clientes.payload_json)
            """,
            (
                telefone_normalizado,
                telefone,
                telefone_normalizado,
                whatsapp_raw_id,
                nome,
                agora,
                agora,
                agora,
                payload_json,
            ),
        )

    def _linha_para_agendamento(self, linha: sqlite3.Row) -> dict:
        dados = dict(linha)
        payload_json = dados.pop("payload_json", None)
        if payload_json:
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                dados.update(payload)
        return {chave: valor for chave, valor in dados.items() if valor is not None}

    def _montar_payload_agendamento(self, dados: dict) -> dict:
        payload = _json_dict(dados.get("payload_json"))
        for chave, valor in dados.items():
            if chave not in AGENDAMENTO_COLUNAS and valor is not None:
                payload[chave] = valor
        return payload

    def _linha_para_solicitacao_humano(self, linha: sqlite3.Row) -> dict | None:
        try:
            dados = json.loads(linha["state_json"])
        except json.JSONDecodeError:
            return None

        state = dados.get("state", dados)
        if not isinstance(state, dict) or not state.get("humano_solicitado"):
            return None

        telefone = state.get("telefone") or linha["telefone"] or linha["telefone_normalizado"]
        return {
            "tipo": "humano",
            "nome": state.get("nome") or linha["nome_cliente"] or "",
            "telefone": telefone,
            "whatsapp": linha["whatsapp_raw_id"] or linha["telefone_normalizado"],
            "categoria": "atendimento humano",
            "descricao": f"Cliente pediu humano na etapa {state.get('etapa_antes_humano') or linha['etapa_atual'] or '-'}",
            "etapa_origem": state.get("etapa_antes_humano") or "",
            "criado_em": linha["atualizado_em"],
            "status": "pendente",
        }

    def _agora(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _historico_com_evento(self, agendamento: dict, evento: dict) -> list[dict]:
        historico = list(agendamento.get("historico", []))
        historico.append(evento)
        return historico


class SQLiteSessionStore:
    def __init__(self, caminho: str | Path | None = None) -> None:
        self.repository = SQLiteAgendaRepository(caminho)

    def exists(self, session_id: str) -> bool:
        client_id = self._client_id(session_id)
        with self.repository._conectar() as conn:
            linha = conn.execute(
                "SELECT 1 FROM sessions WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        return linha is not None

    def get_or_create(self, session_id: str) -> ConversationState:
        client_id = self._client_id(session_id)
        with self.repository._conectar() as conn:
            linha = conn.execute(
                "SELECT state_json FROM sessions WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if linha is None:
            state = ConversationState()
            self.save(session_id, state, finished=False)
            return state
        return self._state_from_json(linha["state_json"])

    def get(self, session_id: str) -> ConversationState:
        return self.get_or_create(session_id)

    def save(self, session_id: str, state: ConversationState, finished: bool = False) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        telefone_normalizado = self._client_id(session_id)
        state_json = json.dumps(
            {"state": asdict(state), "finished": finished},
            ensure_ascii=False,
        )
        with self.repository._lock:
            with self.repository._conectar() as conn:
                with conn:
                    self.repository._upsert_cliente(
                        conn,
                        telefone=session_id,
                        telefone_normalizado=telefone_normalizado,
                        nome=state.nome,
                        whatsapp_raw_id=session_id,
                        payload=None,
                        agora=agora,
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sessions (
                            client_id, telefone_normalizado, state_json, etapa_atual,
                            atualizado_em, expires_at
                        ) VALUES (?, ?, ?, ?, ?, NULL)
                        """,
                        (telefone_normalizado, telefone_normalizado, state_json, state.etapa, agora),
                    )

    def reset(self, session_id: str) -> ConversationState:
        state = ConversationState()
        self.save(session_id, state, finished=False)
        return state

    def delete(self, session_id: str) -> None:
        client_id = self._client_id(session_id)
        with self.repository._lock:
            with self.repository._conectar() as conn:
                with conn:
                    conn.execute("DELETE FROM sessions WHERE client_id = ?", (client_id,))

    def clear(self) -> None:
        with self.repository._lock:
            with self.repository._conectar() as conn:
                with conn:
                    conn.execute("DELETE FROM sessions")

    def is_finished(self, session_id: str) -> bool:
        client_id = self._client_id(session_id)
        with self.repository._conectar() as conn:
            linha = conn.execute(
                "SELECT state_json FROM sessions WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if linha is None:
            return False
        try:
            dados = json.loads(linha["state_json"])
        except json.JSONDecodeError:
            return False
        return bool(dados.get("finished", False))

    def _state_from_json(self, state_json: str) -> ConversationState:
        try:
            dados = json.loads(state_json)
        except json.JSONDecodeError:
            return ConversationState()

        state_data = dados.get("state", dados)
        if not isinstance(state_data, dict):
            return ConversationState()

        campos = {campo.name for campo in fields(ConversationState)}
        return ConversationState(**{chave: valor for chave, valor in state_data.items() if chave in campos})

    def _client_id(self, session_id: str) -> str:
        return _normalizar_telefone_ou_valor(session_id)


def _normalizar_telefone_ou_valor(valor: str) -> str:
    try:
        return normalizar_telefone_whatsapp(valor)
    except ValueError:
        return str(valor or "terminal_demo")


def _lock_para_db(caminho: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        if caminho not in _LOCKS_POR_DB:
            _LOCKS_POR_DB[caminho] = threading.RLock()
        return _LOCKS_POR_DB[caminho]


def _json_dict(valor: Any) -> dict:
    if isinstance(valor, dict):
        return dict(valor)
    if not valor:
        return {}
    try:
        dados = json.loads(str(valor))
    except json.JSONDecodeError:
        return {}
    return dict(dados) if isinstance(dados, dict) else {}
