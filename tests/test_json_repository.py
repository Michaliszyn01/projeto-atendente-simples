from core.storage.json_repository import DEFAULT_AGENDA_PATH, JsonAgendaRepository


def test_repositorio_padrao_aponta_para_data_da_pasta_do_projeto():
    repository = JsonAgendaRepository()

    assert repository.caminho == DEFAULT_AGENDA_PATH
    assert repository.caminho.name == "agenda.json"
    assert repository.caminho.parent.name == "data"


def test_repositorio_cria_arquivo_automaticamente(tmp_path):
    caminho = tmp_path / "agenda.json"

    repository = JsonAgendaRepository(caminho)

    assert caminho.exists()
    assert repository.listar() == []


def test_repositorio_retorna_lista_vazia_para_arquivo_vazio(tmp_path):
    caminho = tmp_path / "agenda.json"
    caminho.write_text("", encoding="utf-8")

    repository = JsonAgendaRepository(caminho)

    assert repository.listar() == []
    assert caminho.read_text(encoding="utf-8").strip() == "[]"


def test_repositorio_recria_json_corrompido_com_lista_vazia(tmp_path):
    caminho = tmp_path / "agenda.json"
    caminho.write_text("{json quebrado", encoding="utf-8")

    repository = JsonAgendaRepository(caminho)

    assert repository.listar() == []
    assert caminho.read_text(encoding="utf-8").strip() == "[]"
