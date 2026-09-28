from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="painel-carrossel-")

# Precisa vir antes de importar app.* — a engine e criada no import de app.db.
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["API_KEY"] = "test-api-key"
os.environ["WORKER_SECRET"] = "test-worker-secret"
os.environ["N8N_WEBHOOK_URL"] = ""
os.environ["API_BASE_URL"] = "http://testserver"
os.environ["MAX_ATTEMPTS"] = "3"
os.environ["MAX_URLS_PER_REQUEST"] = "5"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

API_HEADERS = {"X-API-Key": "test-api-key"}
WORKER_HEADERS = {"X-Worker-Secret": "test-worker-secret"}

URL_INSTAGRAM = "https://www.instagram.com/reel/Cx1y2z3AbCd/"
URL_TIKTOK = "https://www.tiktok.com/@usuario/video/7300000000000000000"


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    sessao = SessionLocal()
    try:
        yield sessao
    finally:
        sessao.close()


@pytest.fixture
def job_id(client) -> str:
    resposta = client.post("/jobs", json={"url": URL_INSTAGRAM}, headers=API_HEADERS)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["criados"][0]["id"]
