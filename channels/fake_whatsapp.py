from channels.base import BaseChannel, IncomingMessage, OutgoingMessage


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

    def receive(self) -> IncomingMessage:
        raise NotImplementedError("FakeWhatsAppChannel não recebe mensagens automaticamente.")

    def send(self, message: OutgoingMessage) -> None:
        self.sent_messages.append(message)
