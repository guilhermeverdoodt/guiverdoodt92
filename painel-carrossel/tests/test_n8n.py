from __future__ import annotations

import httpx
import pytest

from app import n8n
from app.config import get_settings
from app.crud import criar_job
from app.models import Etapa, JobStatus, Plataforma
from tests.conftest import URL_TIKTOK


@pytest.fixture
def webhook_configurado(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "n8n_webhook_url", "https://n8n.exemplo/webhook/teste")
    return settings


def _job(db):
    job = criar_job(db, url=URL_TIKTOK, plataforma=Plataforma.tiktok)
    db.commit()
    return job


def test_payload_tem_callback_e_dados_do_job(db, webhook_configurado):
    job = _job(db)
    payload = n8n.montar_payload(job)
    assert payload["job_id"] == job.id
    assert payload["url"] == URL_TIKTOK
    assert payload["plataforma"] == "tiktok"
    assert payload["callback_url"].endswith(f"/jobs/{job.id}")


def test_disparo_ok_registra_evento(db, webhook_configurado, monkeypatch):
    enviados = []

    def falso_enviar(url, payload, timeout):
        enviados.append((url, payload))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(n8n, "_enviar", falso_enviar)

    job = _job(db)
    n8n.disparar_job(db, job)

    assert len(enviados) == 1
    assert job.status == JobStatus.pendente.value
    assert any(e.etapa == Etapa.dispatch.value for e in job.events)


def test_falha_de_rede_marca_erro_na_etapa_dispatch(db, webhook_configurado, monkeypatch):
    def falso_enviar(url, payload, timeout):
        raise httpx.ConnectError("n8n fora do ar")

    monkeypatch.setattr(n8n, "_enviar", falso_enviar)

    job = _job(db)
    n8n.disparar_job(db, job)

    assert job.status == JobStatus.erro.value
    assert job.etapa == Etapa.dispatch.value
    assert "n8n fora do ar" in job.error


def test_http_500_do_n8n_marca_erro(db, webhook_configurado, monkeypatch):
    def falso_enviar(url, payload, timeout):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(n8n, "_enviar", falso_enviar)

    job = _job(db)
    n8n.disparar_job(db, job)

    assert job.status == JobStatus.erro.value
    assert job.etapa == Etapa.dispatch.value


def test_job_com_erro_de_dispatch_pode_ser_reprocessado(client, monkeypatch):
    """Erro no disparo deixa o job visivel e retryable pelo painel."""
    settings = get_settings()
    monkeypatch.setattr(settings, "n8n_webhook_url", "https://n8n.exemplo/webhook/teste")
    monkeypatch.setattr(
        n8n,
        "_enviar",
        lambda url, payload, timeout: (_ for _ in ()).throw(httpx.ConnectError("off")),
    )

    from tests.conftest import API_HEADERS

    criado = client.post("/jobs", json={"url": URL_TIKTOK}, headers=API_HEADERS)
    job_id = criado.json()["criados"][0]["id"]

    detalhe = client.get(f"/jobs/{job_id}", headers=API_HEADERS).json()
    assert detalhe["status"] == "erro"
    assert detalhe["etapa"] == "dispatch"

    retry = client.post(f"/jobs/{job_id}/retry", headers=API_HEADERS)
    assert retry.status_code == 200
    assert retry.json()["attempts"] == 1
