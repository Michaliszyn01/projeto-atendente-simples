from channels.base import OutgoingMessage
from channels.terminal import TerminalChannel
from core.config.config_loader import ConfigError
from core.conversation.engine import ConversationEngine


def run_terminal_app(session_id: str = "terminal") -> None:
    try:
        engine = ConversationEngine()
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}")
        return

    channel = TerminalChannel(sender_id=session_id)
    channel.send(
        OutgoingMessage(
            channel=channel.channel_name,
            recipient_id=session_id,
            text=engine.start(session_id),
        )
    )

    while not engine.is_finished(session_id):
        incoming = channel.receive()
        resposta = engine.process_message(incoming.sender_id, incoming.text)
        channel.send(
            OutgoingMessage(
                channel=incoming.channel,
                recipient_id=incoming.sender_id,
                text=resposta,
            )
        )

        if incoming.text.strip().lower() == "sair":
            break
