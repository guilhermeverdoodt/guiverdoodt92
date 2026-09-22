from __future__ import annotations

from tests.conftest import API_HEADERS, URL_INSTAGRAM, WORKER_HEADERS


def test_sem_api_key_bloqueia(client):
    assert client.get("/jobs").status_code == 401
    assert client.post("/jobs", json={"url": URL_INSTAGRAM}).status_code == 401


def test_api_key_errada_bloqueia(client):
    resposta = client.get("/jobs", headers={"X-API-Key": "errada"})
    assert resposta.status_code == 401


def test_healthz_e_publico(client):
    resposta = client.get("/healthz")
    assert resposta.status_code == 200
    assert resposta.json()["database"] == "ok"


def test_patch_exige_segredo_do_worker(client, job_id):
    # API key do painel nao vale no callback do worker
    resposta = client.patch(
        f"/jobs/{job_id}", json={"status": "processando"}, headers=API_HEADERS
    )
    assert resposta.status_code == 401

    resposta = client.patch(
        f"/jobs/{job_id}", json={"status": "processando"}, headers=WORKER_HEADERS
    )
    assert resposta.status_code == 200


def test_assinatura_hmac_do_webhook():
    from app.security import assinar_payload

    assinatura = assinar_payload(b'{"job_id":"abc"}')
    assert assinatura.startswith("sha256=")
    assert assinatura == assinar_payload(b'{"job_id":"abc"}')
    assert assinatura != assinar_payload(b'{"job_id":"xyz"}')
