from channels.base import BaseChannel, IncomingMessage, OutgoingMessage
from core.scheduling.validators import normalizar_telefone_whatsapp


class FakeWhatsAppChannel(BaseChannel):
    channel_name = "fake_whatsapp"

    def __init__(self) -> None:
        self.sent_messages: list[OutgoingMessage] = []

    def build_incoming(self, phone: str, text: str) -> IncomingMessage:
        return IncomingMessage(
            channel=self.channel_name,
            sender_id=phone,
            text=text,
            raw={"phone": phone, "text": text},
        )

    def build_incoming_from_payload(self, payload: dict) -> IncomingMessage:
        phone = payload.get("from") or payload.get("telefone") or payload.get("phone")
        text = payload.get("message") or payload.get("mensagem") or payload.get("text")

        if not phone:
            raise ValueError("Payload sem telefone de origem.")
        if text is None:
            raise ValueError("Payload sem mensagem.")

        return IncomingMessage(
            channel=self.channel_name,
            sender_id=normalizar_telefone_whatsapp(str(phone)),
            text=str(text),
            raw=dict(payload),
        )

    def build_incoming_payload(self, payload: dict) -> IncomingMessage:
        return self.build_incoming_from_payload(payload)

    def receive(self) -> IncomingMessage:
        raise NotImplementedError("FakeWhatsAppChannel não recebe mensagens automaticamente.")

    def send(self, message: OutgoingMessage) -> None:
        self.sent_messages.append(message)
