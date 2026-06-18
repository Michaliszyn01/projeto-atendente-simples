from core.config.config_loader import ConfigError
from core.conversation.engine import ConversationEngine


def run_terminal_app(session_id: str = "terminal") -> None:
    try:
        engine = ConversationEngine()
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}")
        return

    print(engine.start(session_id))

    while not engine.is_finished(session_id):
        mensagem = input("> ")
        resposta = engine.process_message(session_id, mensagem)
        print(resposta)

        if mensagem.strip().lower() == "sair":
            break
