from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**kwargs) -> Settings:
    base = {"api_key": "chave-boa-o-suficiente", "worker_secret": "segredo-bom-o-suficiente"}
    base.update(kwargs)
    # _env_file=None isola o teste de um .env presente na maquina
    return Settings(_env_file=None, **base)


def test_segredos_validos_passam():
    s = _settings()
    assert s.api_key == "chave-boa-o-suficiente"


@pytest.mark.parametrize(
    "valor", ["dev-api-key", "dev-worker-secret", "troque-esta-chave", "changeme", "secret"]
)
def test_placeholder_e_recusado(valor):
    with pytest.raises(ValidationError, match="valor de exemplo"):
        _settings(api_key=valor)


@pytest.mark.parametrize("valor", ["", "curta", "1234567"])
def test_segredo_curto_e_recusado(valor):
    with pytest.raises(ValidationError, match="ao menos 8 caracteres"):
        _settings(worker_secret=valor)


def test_segredo_ausente_e_recusado(monkeypatch):
    monkeypatch.delenv("WORKER_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_key="chave-boa-o-suficiente")
