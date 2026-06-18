from core.config.config_loader import carregar_config


def _config_atual() -> dict:
    return carregar_config()


def obter_servicos() -> dict[str, int]:
    return dict(_config_atual().get("servicos", {}))


def obter_profissionais() -> list[str]:
    return list(_config_atual().get("profissionais", []))


def obter_horarios_por_periodo() -> dict[str, list[str]]:
    return dict(_config_atual().get("horarios", {}))
