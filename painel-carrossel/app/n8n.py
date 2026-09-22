"""Disparo do webhook para o n8n (orquestrador do pipeline)."""
from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud import registrar_evento
from app.models import Etapa, Job, JobStatus

logger = logging.getLogger(__name__)


def montar_payload(job: Job, callback_base_url: str | None = None) -> dict:
    settings = get_settings()
    base = (callback_base_url or settings.api_base_url).rstrip("/")
    return {
        "job_id": job.id,
        "url": job.url,
        "plataforma": job.plataforma,
        "attempts": job.attempts,
        "callback_url": f"{base}/jobs/{job.id}",
    }


def _enviar(url: str, payload: dict, timeout: float) -> httpx.Response:
    """Isolado para facilitar o mock nos testes."""
    from app.security import SIGNATURE_HEADER, assinar_payload

    # ensure_ascii=False + separadores compactos = mesmos bytes que o
    # JSON.stringify do Code node no n8n, para o HMAC bater dos dois lados.
    corpo = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: assinar_payload(corpo),
    }
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, content=corpo, headers=headers)


def disparar_job(db: Session, job: Job) -> None:
    """Avisa o n8n que ha trabalho. Falha de rede vira status `erro` na etapa
    `dispatch` — assim o job aparece no painel e pode ser reprocessado.
    """
    settings = get_settings()

    if not settings.n8n_webhook_url:
        registrar_evento(
            db,
            job,
            etapa=Etapa.dispatch,
            status=JobStatus(job.status),
            mensagem="N8N_WEBHOOK_URL nao configurada — job criado sem disparo.",
        )
        db.commit()
        logger.warning("N8N_WEBHOOK_URL vazia; job %s ficou pendente.", job.id)
        return

    payload = montar_payload(job)
    try:
        resposta = _enviar(
            settings.n8n_webhook_url, payload, settings.n8n_timeout_seconds
        )
        resposta.raise_for_status()
    except Exception as exc:  # httpx.HTTPError e afins
        job.status = JobStatus.erro.value
        job.etapa = Etapa.dispatch.value
        job.error = f"Falha ao acionar o n8n: {exc}"
        registrar_evento(
            db,
            job,
            etapa=Etapa.dispatch,
            status=JobStatus.erro,
            mensagem=job.error,
        )
        db.commit()
        logger.exception("Falha ao disparar o job %s para o n8n", job.id)
        return

    registrar_evento(
        db,
        job,
        etapa=Etapa.dispatch,
        status=JobStatus(job.status),
        mensagem="Webhook enviado ao n8n.",
    )
    db.commit()


def disparar_job_por_id(job_id: str) -> None:
    """Versao para BackgroundTasks: abre a propria sessao de banco."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("Job %s sumiu antes do disparo.", job_id)
            return
        disparar_job(db, job)
    finally:
        db.close()
