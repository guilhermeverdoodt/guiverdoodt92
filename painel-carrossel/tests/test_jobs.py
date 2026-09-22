from __future__ import annotations

from tests.conftest import API_HEADERS, URL_INSTAGRAM, URL_TIKTOK, WORKER_HEADERS


def test_cria_job_com_uma_url(client):
    resposta = client.post("/jobs", json={"url": URL_INSTAGRAM}, headers=API_HEADERS)
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert len(corpo["criados"]) == 1
    job = corpo["criados"][0]
    assert job["plataforma"] == "instagram"
    assert job["status"] == "pendente"
    assert job["attempts"] == 0
    assert corpo["rejeitados"] == []


def test_cria_varios_jobs_e_deduplica(client):
    resposta = client.post(
        "/jobs",
        json={"urls": [URL_INSTAGRAM, URL_TIKTOK, URL_INSTAGRAM]},
        headers=API_HEADERS,
    )
    assert resposta.status_code == 201
    criados = resposta.json()["criados"]
    assert len(criados) == 2
    assert {j["plataforma"] for j in criados} == {"instagram", "tiktok"}


def test_url_invalida_no_lote_nao_derruba_o_resto(client):
    resposta = client.post(
        "/jobs",
        json={"urls": [URL_TIKTOK, "https://youtube.com/watch?v=abc"]},
        headers=API_HEADERS,
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert len(corpo["criados"]) == 1
    assert len(corpo["rejeitados"]) == 1
    assert "nao suportada" in corpo["rejeitados"][0]["motivo"]


def test_lote_todo_invalido_retorna_422(client):
    resposta = client.post(
        "/jobs", json={"urls": ["https://youtube.com/watch?v=abc"]}, headers=API_HEADERS
    )
    assert resposta.status_code == 422


def test_limite_de_urls_por_requisicao(client):
    urls = [f"https://www.tiktok.com/@u/video/73000000000000000{i}" for i in range(6)]
    resposta = client.post("/jobs", json={"urls": urls}, headers=API_HEADERS)
    assert resposta.status_code == 422
    assert "Maximo de 5" in resposta.json()["detail"]


def test_payload_sem_url(client):
    assert client.post("/jobs", json={}, headers=API_HEADERS).status_code == 422


def test_detalhe_traz_historico(client, job_id):
    resposta = client.get(f"/jobs/{job_id}", headers=API_HEADERS)
    assert resposta.status_code == 200
    corpo = resposta.json()
    etapas = [e["etapa"] for e in corpo["events"]]
    assert "recebido" in etapas
    # sem N8N_WEBHOOK_URL configurada, o disparo registra o aviso e nao quebra
    assert "dispatch" in etapas


def test_detalhe_inexistente(client):
    assert client.get("/jobs/naoexiste", headers=API_HEADERS).status_code == 404


def test_lista_filtra_por_status_e_plataforma(client):
    client.post("/jobs", json={"urls": [URL_INSTAGRAM, URL_TIKTOK]}, headers=API_HEADERS)

    todos = client.get("/jobs", headers=API_HEADERS).json()
    assert todos["total"] == 2

    so_tiktok = client.get("/jobs?plataforma=tiktok", headers=API_HEADERS).json()
    assert so_tiktok["total"] == 1
    assert so_tiktok["items"][0]["plataforma"] == "tiktok"

    concluidos = client.get("/jobs?status=concluido", headers=API_HEADERS).json()
    assert concluidos["total"] == 0


def test_stats(client, job_id):
    corpo = client.get("/jobs/stats", headers=API_HEADERS).json()
    assert corpo["pendente"] == 1
    assert corpo["total"] == 1


def test_fluxo_completo_via_patch(client, job_id):
    etapas = [
        {"status": "processando", "etapa": "download", "mensagem": "yt-dlp ok"},
        {"etapa": "audio", "mensagem": "ffmpeg ok"},
        {"etapa": "transcricao", "transcript": "texto transcrito do video"},
        {
            "etapa": "slides",
            "slides_json": {
                "titulo": "5 erros de copy",
                "slides": [{"n": 1, "texto": "Erro 1"}],
                "cta": "Salva esse post",
            },
        },
        {
            "status": "concluido",
            "etapa": "carrossel",
            "carousel_url": "https://canva.com/design/abc",
        },
    ]
    for etapa in etapas:
        resposta = client.patch(f"/jobs/{job_id}", json=etapa, headers=WORKER_HEADERS)
        assert resposta.status_code == 200, resposta.text

    job = client.get(f"/jobs/{job_id}", headers=API_HEADERS).json()
    assert job["status"] == "concluido"
    assert job["transcript"] == "texto transcrito do video"
    assert job["slides_json"]["titulo"] == "5 erros de copy"
    assert job["carousel_url"] == "https://canva.com/design/abc"
    assert job["error"] is None
    assert [e["etapa"] for e in job["events"]][-1] == "carrossel"


def test_patch_com_erro_marca_status_erro(client, job_id):
    resposta = client.patch(
        f"/jobs/{job_id}",
        json={"etapa": "download", "error": "yt-dlp: HTTP 403 (anti-bot)"},
        headers=WORKER_HEADERS,
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "erro"
    assert corpo["etapa"] == "download"
    assert "403" in corpo["error"]


def test_patch_job_inexistente(client):
    resposta = client.patch(
        "/jobs/naoexiste", json={"status": "processando"}, headers=WORKER_HEADERS
    )
    assert resposta.status_code == 404


def test_retry_apos_erro(client, job_id):
    client.patch(
        f"/jobs/{job_id}",
        json={"etapa": "download", "error": "yt-dlp quebrou"},
        headers=WORKER_HEADERS,
    )
    resposta = client.post(f"/jobs/{job_id}/retry", headers=API_HEADERS)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "pendente"
    assert corpo["error"] is None
    assert corpo["attempts"] == 1


def test_retry_bloqueado_enquanto_processa(client, job_id):
    client.patch(f"/jobs/{job_id}", json={"status": "processando"}, headers=WORKER_HEADERS)
    resposta = client.post(f"/jobs/{job_id}/retry", headers=API_HEADERS)
    assert resposta.status_code == 409


def test_retry_respeita_limite_de_tentativas(client, job_id):
    for _ in range(3):
        client.patch(
            f"/jobs/{job_id}", json={"error": "falhou de novo"}, headers=WORKER_HEADERS
        )
        assert client.post(f"/jobs/{job_id}/retry", headers=API_HEADERS).status_code == 200

    client.patch(f"/jobs/{job_id}", json={"error": "falhou"}, headers=WORKER_HEADERS)
    resposta = client.post(f"/jobs/{job_id}/retry", headers=API_HEADERS)
    assert resposta.status_code == 409
    assert "3 tentativas" in resposta.json()["detail"]


def test_retry_job_inexistente(client):
    assert client.post("/jobs/naoexiste/retry", headers=API_HEADERS).status_code == 404
