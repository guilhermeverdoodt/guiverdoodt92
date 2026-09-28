"""Modelo de dados: jobs + historico de etapas."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    """Ciclo de vida do job."""

    pendente = "pendente"       # criado, aguardando o worker
    processando = "processando"  # n8n assumiu
    concluido = "concluido"      # carrossel gerado
    erro = "erro"                # falhou em alguma etapa


class Plataforma(str, enum.Enum):
    instagram = "instagram"
    tiktok = "tiktok"
    desconhecida = "desconhecida"


class Etapa(str, enum.Enum):
    """Etapas do pipeline — o que estava rodando quando deu erro."""

    recebido = "recebido"
    dispatch = "dispatch"          # envio do webhook para o n8n
    download = "download"          # yt-dlp
    audio = "audio"                # ffmpeg
    transcricao = "transcricao"    # faster-whisper
    slides = "slides"              # LLM via Groq
    carrossel = "carrossel"        # Claude Design MCP / Canva
    finalizado = "finalizado"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    plataforma: Mapped[str] = mapped_column(
        String(20), nullable=False, default=Plataforma.desconhecida.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.pendente.value, index=True
    )
    etapa: Mapped[str] = mapped_column(
        String(20), nullable=False, default=Etapa.recebido.value
    )

    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    slides_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    carousel_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEvent.created_at",
    )


class JobEvent(Base):
    """Log das transicoes — essencial para saber qual etapa quebrou."""

    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    etapa: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    mensagem: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )

    job: Mapped[Job] = relationship(back_populates="events")
