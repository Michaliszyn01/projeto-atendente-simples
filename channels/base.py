from dataclasses import dataclass
from typing import Any


@dataclass
class IncomingMessage:
    channel: str
    sender_id: str
    text: str
    raw: dict[str, Any] | None = None


@dataclass
class OutgoingMessage:
    channel: str
    recipient_id: str
    text: str
    raw: dict[str, Any] | None = None


class BaseChannel:
    channel_name: str

    def receive(self) -> IncomingMessage:
        raise NotImplementedError

    def send(self, message: OutgoingMessage) -> None:
        raise NotImplementedError
