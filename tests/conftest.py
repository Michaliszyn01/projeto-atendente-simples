from pathlib import Path
import re
import shutil
from uuid import uuid4

import pytest


@pytest.fixture
def tmp_path(request):
    base = Path("pytest_tmp")
    base.mkdir(exist_ok=True)
    nome = re.sub(r"[^a-zA-Z0-9_-]+", "_", request.node.name)[:40]
    caminho = base / f"{nome}_{uuid4().hex}"
    caminho.mkdir(parents=True, exist_ok=False)

    try:
        yield caminho
    finally:
        shutil.rmtree(caminho, ignore_errors=True)
