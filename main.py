from core.config.config_loader import ConfigError
from core.conversation.flow import AtendimentoFlow
from core.storage.json_repository import JsonAgendaRepository


def main() -> None:
    try:
        repository = JsonAgendaRepository()
        flow = AtendimentoFlow(repository)
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}")
        return

    print(flow.iniciar())

    while not flow.encerrado:
        mensagem = input("> ")
        resposta = flow.receber(mensagem)
        print(resposta)


if __name__ == "__main__":
    main()
