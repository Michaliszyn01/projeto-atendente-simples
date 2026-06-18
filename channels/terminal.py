from channels.base import BaseChannel, IncomingMessage, OutgoingMessage


class TerminalChannel(BaseChannel):
    channel_name = "terminal"

    def __init__(self, sender_id: str = "terminal") -> None:
        self.sender_id = sender_id

    def receive(self) -> IncomingMessage:
        return IncomingMessage(
            channel=self.channel_name,
            sender_id=self.sender_id,
            text=input("> "),
        )

    def send(self, message: OutgoingMessage) -> None:
        print(message.text)
