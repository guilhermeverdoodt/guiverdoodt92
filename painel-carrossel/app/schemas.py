"""Schemas de entrada e saida da API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Etapa, JobStatus, Plataforma


class JobCreate(BaseModel):
    """Aceita uma URL (`url`) ou varias (`urls`) — pelo menos uma das duas."""

    url: str | None = None
    urls: list[str] | None = None

    @model_validator(mode="after")
    def _pelo_menos_uma(self) -> "JobCreate":
        # checa o resultado de todas_urls(), nao os campos crus: um lote so com
        # linhas em branco ("urls": ["  "]) passaria e criaria zero jobs com 201.
        if not self.todas_urls():
            raise ValueError("Informe ao menos uma URL nao vazia em 'url' ou 'urls'.")
        return self

    def todas_urls(self) -> list[str]:
        itens = list(self.urls or [])
        if self.url:
            itens.insert(0, self.url)
        # remove duplicatas preservando a ordem
        vistos: set[str] = set()
        saida: list[str] = []
        for item in itens:
            chave = item.strip()
            if chave and chave not in vistos:
                vistos.add(chave)
                saida.append(chave)
        return saida


class JobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    etapa: str
    status: str
    mensagem: str | None = None
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    plataforma: Plataforma
    status: JobStatus
    etapa: Etapa
    transcript: str | None = None
    slides_json: Any | None = None
    carousel_url: str | None = None
    error: str | None = None
    attempts: int
    created_at: datetime
    updated_at: datetime


class JobDetailOut(JobOut):
    events: list[JobEventOut] = Field(default_factory=list)


class JobListOut(BaseModel):
    total: int
    items: list[JobOut]


class JobCreateOut(BaseModel):
    """Resultado de POST /jobs: o que foi aceito e o que foi rejeitado."""

    criados: list[JobOut] = Field(default_factory=list)
    rejeitados: list[dict[str, str]] = Field(default_factory=list)


class JobPatch(BaseModel):
    """Callback do n8n. Todos os campos sao opcionais — o worker manda o que tem."""

    # Numero da tentativa que o worker recebeu no webhook. Quando vem
    # preenchido, a API recusa o callback se nao for a tentativa corrente —
    # e o que impede uma execucao atrasada de sobrescrever o retry.
    attempt: int | None = None
    status: JobStatus | None = None
    etapa: Etapa | None = None
    transcript: str | None = None
    slides_json: Any | None = None
    carousel_url: str | None = None
    error: str | None = None
    mensagem: str | None = None  # linha de log para o historico
