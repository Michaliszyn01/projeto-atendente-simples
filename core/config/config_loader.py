import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"


class ConfigError(Exception):
    pass


def carregar_config(caminho: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(caminho) if caminho is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    if not config_path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {config_path}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Arquivo de configuração inválido: {exc}") from exc

    if not isinstance(config, dict):
        raise ConfigError("Arquivo de configuração deve conter um objeto JSON.")

    validar_config(config)
    return config


def validar_config(config: dict[str, Any]) -> None:
    obrigatorios = [
        "modo",
        "usa_agendamento",
        "usa_profissional",
        "opcoes_inicio",
        "mensagens",
    ]
    validar_campos(config, obrigatorios, "config")

    if config["modo"] not in {"barbearia", "clinica", "loja"}:
        raise ConfigError("Campo 'modo' deve ser barbearia, clinica ou loja.")
    if not isinstance(config["usa_agendamento"], bool):
        raise ConfigError("Campo 'usa_agendamento' deve ser true ou false.")
    if not isinstance(config["usa_profissional"], bool):
        raise ConfigError("Campo 'usa_profissional' deve ser true ou false.")
    if not lista_de_textos(config["opcoes_inicio"]):
        raise ConfigError("Campo 'opcoes_inicio' deve ser uma lista de textos.")
    if not isinstance(config["mensagens"], dict):
        raise ConfigError("Campo 'mensagens' deve ser um objeto.")

    for campo in [
        "nome_estabelecimento",
        "endereco",
        "telefone_estabelecimento",
        "instagram",
        "cidade",
        "estado",
    ]:
        if campo in config and not isinstance(config[campo], str):
            raise ConfigError(f"Campo '{campo}' deve ser texto quando informado.")

    validar_campos(config["mensagens"], ["inicio", "humano"], "mensagens")

    if config["usa_agendamento"]:
        validar_config_agendamento(config)
    elif config["modo"] == "loja":
        validar_config_loja(config)


def validar_config_agendamento(config: dict[str, Any]) -> None:
    validar_campos(
        config,
        ["nome_profissional", "nome_servico", "servicos", "profissionais", "horarios"],
        "config",
    )
    validar_campos(
        config["mensagens"],
        [
            "pergunta_dia",
            "pergunta_servico",
            "pergunta_profissional",
            "pergunta_periodo",
            "pergunta_nome",
            "pergunta_telefone",
            "consulta_pede_telefone",
            "cancelamento_pede_telefone",
            "confirmacao_cancelamento",
            "cancelamento_confirmado",
            "agendamento_nao_encontrado",
            "menu_inicial",
        ],
        "mensagens",
    )

    if not isinstance(config["servicos"], dict) or not config["servicos"]:
        raise ConfigError("Campo 'servicos' deve ser um objeto com pelo menos um serviço.")
    for servico, duracao in config["servicos"].items():
        if not isinstance(servico, str) or not servico.strip():
            raise ConfigError("Todos os nomes em 'servicos' devem ser textos.")
        if not isinstance(duracao, int) or duracao <= 0:
            raise ConfigError("Todas as durações em 'servicos' devem ser números positivos.")

    if config["usa_profissional"] and not lista_de_textos(config["profissionais"]):
        raise ConfigError("Campo 'profissionais' deve ser uma lista de textos.")

    if not isinstance(config["horarios"], dict) or not config["horarios"]:
        raise ConfigError("Campo 'horarios' deve ser um objeto com períodos.")
    for periodo, horarios in config["horarios"].items():
        if not isinstance(periodo, str) or not periodo.strip():
            raise ConfigError("Todos os períodos em 'horarios' devem ter nome.")
        if not lista_de_textos(horarios):
            raise ConfigError("Cada período em 'horarios' deve ter uma lista de horários.")


def validar_config_loja(config: dict[str, Any]) -> None:
    validar_campos(config, ["categorias"], "config")
    validar_campos(config["mensagens"], ["pergunta_categoria", "pergunta_orcamento", "pergunta_nome"], "mensagens")
    if not lista_de_textos(config["categorias"]):
        raise ConfigError("Campo 'categorias' deve ser uma lista de textos.")


def validar_campos(dados: dict[str, Any], campos: list[str], nome: str) -> None:
    faltando = [campo for campo in campos if campo not in dados]
    if faltando:
        raise ConfigError(f"Campo(s) obrigatório(s) ausente(s) em {nome}: {', '.join(faltando)}")


def lista_de_textos(valor: Any) -> bool:
    return isinstance(valor, list) and bool(valor) and all(isinstance(item, str) and item.strip() for item in valor)
