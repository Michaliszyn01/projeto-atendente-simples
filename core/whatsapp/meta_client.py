import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx


logger = logging.getLogger(__name__)
DEFAULT_GRAPH_VERSION = "v20.0"


@dataclass(frozen=True)
class MetaWhatsAppConfig:
    token: str | None
    phone_number_id: str | None
    graph_version: str = DEFAULT_GRAPH_VERSION

    @classmethod
    def from_env(cls) -> "MetaWhatsAppConfig":
        return cls(
            token=_env_text("META_WHATSAPP_TOKEN"),
            phone_number_id=_env_text("META_WHATSAPP_PHONE_NUMBER_ID"),
            graph_version=_env_text("META_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION,
        )

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.token:
            missing.append("META_WHATSAPP_TOKEN")
        if not self.phone_number_id:
            missing.append("META_WHATSAPP_PHONE_NUMBER_ID")
        return missing


class MetaWhatsAppClient:
    def __init__(
        self,
        config: MetaWhatsAppConfig | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config or MetaWhatsAppConfig.from_env()
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "MetaWhatsAppClient":
        return cls(MetaWhatsAppConfig.from_env())

    def send_text_message(self, to: str, text: str) -> dict[str, Any]:
        missing = self.config.missing_fields()
        if missing:
            return {
                "ok": False,
                "error": "Configuracao da Meta incompleta.",
                "missing": missing,
            }

        url = (
            f"https://graph.facebook.com/{self.config.graph_version}/"
            f"{self.config.phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Meta Cloud API retornou erro HTTP: %s", exc.response.status_code)
            return {
                "ok": False,
                "error": "Meta Cloud API retornou erro HTTP.",
                "status_code": exc.response.status_code,
                "response": _response_json_ou_texto(exc.response),
            }
        except httpx.HTTPError as exc:
            logger.warning("Falha ao chamar Meta Cloud API: %s", exc)
            return {
                "ok": False,
                "error": "Falha ao chamar Meta Cloud API.",
                "detail": str(exc),
            }

        return {
            "ok": True,
            "status_code": response.status_code,
            "response": _response_json_ou_texto(response),
        }


def _env_text(nome: str) -> str | None:
    valor = os.getenv(nome)
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None


def _response_json_ou_texto(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
