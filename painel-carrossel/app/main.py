"""Painel de Transcricao e Geracao de Carrossel — API."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import init_db
from app.routers import health, jobs

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()
    if not settings.n8n_webhook_url:
        logger.warning(
            "N8N_WEBHOOK_URL nao configurada: todo job criado vai falhar na etapa dispatch."
        )
    yield


app = FastAPI(
    title="Painel de Transcricao e Carrossel",
    description=(
        "Recebe videos do Instagram/TikTok, orquestra a transcricao no n8n "
        "e acompanha a geracao do carrossel."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(jobs.router)


@app.get("/", tags=["infra"])
def raiz() -> dict:
    return {"servico": "painel-carrossel", "docs": "/docs"}
