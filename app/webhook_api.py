import os
import logging
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from core.conversation.engine import ConversationEngine
from core.scheduling.validators import normalizar_telefone_whatsapp
from core.storage.sqlite_repository import SQLiteAgendaRepository
from core.whatsapp.meta_client import MetaWhatsAppClient


app = FastAPI(title="Projeto Atendente Simples")
logger = logging.getLogger(__name__)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "atendente-whatsapp",
        "storage": "sqlite",
    }


@app.post("/webhook/whatsapp")
def receber_whatsapp(
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> JSONResponse:
    erro_auth = _validar_api_key(x_api_key)
    if erro_auth is not None:
        return erro_auth

    telefone_bruto = payload.get("from") or payload.get("telefone") or payload.get("phone")
    mensagem = payload.get("message") or payload.get("mensagem") or payload.get("text")

    if not telefone_bruto:
        return _erro("Payload sem telefone de origem.", status_code=400)
    if mensagem is None or str(mensagem).strip() == "":
        return _erro("Payload sem mensagem.", status_code=400)

    try:
        telefone = normalizar_telefone_whatsapp(str(telefone_bruto))
    except ValueError:
        return _erro("Telefone de WhatsApp inválido.", status_code=400)

    engine = _get_engine()
    reply = engine.process_message(telefone, str(mensagem))
    state = engine.session_store.get_or_create(telefone)

    return JSONResponse(
        {
            "ok": True,
            "to": telefone,
            "reply": reply,
            "human_requested": bool(getattr(state, "humano_solicitado", False)),
        }
    )


@app.get("/webhook/meta")
def verificar_webhook_meta(request: Request):
    modo = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    token_configurado = os.getenv("META_WHATSAPP_VERIFY_TOKEN")

    if modo == "subscribe" and token_configurado and verify_token == token_configurado and challenge is not None:
        return PlainTextResponse(challenge)

    return _erro("Meta webhook verification failed.", status_code=403)


@app.post("/webhook/meta")
def receber_meta(payload: dict[str, Any]) -> JSONResponse:
    mensagens = _extrair_mensagens_meta(payload)
    if not mensagens:
        return JSONResponse({"ok": True, "processed": 0, "ignored": True})

    engine = _get_engine()
    repository = _get_sqlite_repository(engine)
    meta_client = _get_meta_client()
    processed = 0
    duplicated = 0
    sent = 0
    send_errors: list[dict[str, Any]] = []

    for mensagem in mensagens:
        message_id_externo = mensagem.get("message_id_externo")
        if message_id_externo and repository is not None and repository.mensagem_externa_processada(message_id_externo):
            duplicated += 1
            continue

        try:
            telefone = normalizar_telefone_whatsapp(str(mensagem["telefone"]))
        except ValueError:
            logger.warning("Meta webhook ignorado: telefone invalido.")
            continue

        texto = str(mensagem["texto"])
        reply = engine.process_message(telefone, texto)
        processed += 1

        if repository is not None:
            repository.registrar_mensagem(
                telefone=telefone,
                direcao="entrada",
                mensagem=texto,
                canal="meta",
                message_id_externo=message_id_externo,
                payload=payload,
            )

        send_result = meta_client.send_text_message(telefone, reply)
        if send_result.get("ok"):
            sent += 1
        else:
            logger.warning("Falha ao enviar resposta pela Meta: %s", send_result.get("error"))
            send_errors.append(send_result)

        if repository is not None:
            repository.registrar_mensagem(
                telefone=telefone,
                direcao="saida",
                mensagem=reply,
                canal="meta",
                payload={"send_result": send_result},
            )

    body: dict[str, Any] = {"ok": True, "processed": processed}
    if duplicated:
        body["duplicated"] = duplicated
    if sent:
        body["sent"] = sent
    if send_errors:
        body["send_errors"] = send_errors
    if processed == 0 and duplicated == 0:
        body["ignored"] = True
    return JSONResponse(body)


def _get_engine() -> ConversationEngine:
    engine = getattr(app.state, "engine", None)
    if engine is None:
        engine = ConversationEngine()
        app.state.engine = engine
    return engine


def _get_meta_client() -> MetaWhatsAppClient:
    client = getattr(app.state, "meta_client", None)
    if client is None:
        client = MetaWhatsAppClient.from_env()
        app.state.meta_client = client
    return client


def _get_sqlite_repository(engine: ConversationEngine) -> SQLiteAgendaRepository | None:
    repository = getattr(engine, "agenda_repository", None)
    if isinstance(repository, SQLiteAgendaRepository):
        return repository
    return None


def _extrair_mensagens_meta(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    mensagens_extraidas: list[dict[str, str | None]] = []
    for entry in _lista(payload.get("entry")):
        for change in _lista(entry.get("changes")):
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            for mensagem in _lista(value.get("messages")):
                if not isinstance(mensagem, dict) or mensagem.get("type") != "text":
                    continue
                text = mensagem.get("text")
                body = text.get("body") if isinstance(text, dict) else None
                remetente = mensagem.get("from")
                if remetente and body is not None and str(body).strip():
                    mensagens_extraidas.append(
                        {
                            "telefone": str(remetente),
                            "texto": str(body),
                            "message_id_externo": _texto_ou_none(mensagem.get("id")),
                        }
                    )
    return mensagens_extraidas


def _lista(valor: Any) -> list[Any]:
    return valor if isinstance(valor, list) else []


def _texto_ou_none(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _validar_api_key(api_key_recebida: str | None) -> JSONResponse | None:
    api_key_configurada = _api_key_configurada()
    if api_key_configurada is None:
        return _erro("WEBHOOK_API_KEY nao configurada.", status_code=500)
    if api_key_recebida != api_key_configurada:
        return _erro("unauthorized", status_code=401)
    return None


def _api_key_configurada() -> str | None:
    valor = os.getenv("WEBHOOK_API_KEY")
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None


def _erro(mensagem: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": mensagem},
        status_code=status_code,
    )
