from pathlib import Path

import pytest

from core.config.config_loader import ConfigError, PROJECT_ROOT, carregar_config


def test_carregamento_valido_do_config_principal():
    config = carregar_config()

    assert config["modo"] == "barbearia"
    assert config["usa_agendamento"] is True
    assert "corte" in config["servicos"]


def test_config_ausente_gera_erro_claro(tmp_path):
    caminho = tmp_path / "config.json"

    with pytest.raises(ConfigError, match="não encontrado"):
        carregar_config(caminho)


def test_barbearia_carrega_servicos_e_profissionais():
    config = carregar_config(PROJECT_ROOT / "exemplos" / "barbearia.json")

    assert config["servicos"]["corte"] == 30
    assert config["profissionais"] == ["Marcos", "Julio"]


def test_clinica_usa_medico_como_nome_de_profissional():
    config = carregar_config(PROJECT_ROOT / "exemplos" / "clinica.json")

    assert config["modo"] == "clinica"
    assert config["nome_profissional"] == "médico"
    assert "médico" in config["mensagens"]["pergunta_profissional"]
