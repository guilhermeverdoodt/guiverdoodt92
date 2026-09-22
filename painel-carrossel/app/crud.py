"""Operacoes de banco sobre jobs."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Etapa, Job, JobEvent, JobStatus, Plataforma, utcnow

# Status a partir dos quais faz sentido reprocessar.
STATUS_REPROCESSAVEIS = {JobStatus.erro, JobStatus.concluido}


def registrar_evento(
    db: Session,
    job: Job,
    *,
    etapa: Etapa,
    status: JobStatus,
    mensagem: str | None = None,
) -> JobEvent:
    evento = JobEvent(
        job_id=job.id,
        etapa=etapa.value,
        status=status.value,
        mensagem=mensagem,
    )
    db.add(evento)
    return evento


def criar_job(db: Session, *, url: str, plataforma: Plataforma) -> Job:
    job = Job(
        url=url,
        plataforma=plataforma.value,
        status=JobStatus.pendente.value,
        etapa=Etapa.recebido.value,
    )
    db.add(job)
    db.flush()  # garante o id antes do evento
    registrar_evento(
        db, job, etapa=Etapa.recebido, status=JobStatus.pendente, mensagem="Job criado."
    )
    return job


def buscar_job(db: Session, job_id: str, *, com_eventos: bool = False) -> Job | None:
    stmt = select(Job).where(Job.id == job_id)
    if com_eventos:
        stmt = stmt.options(selectinload(Job.events))
    return db.execute(stmt).scalar_one_or_none()


def listar_jobs(
    db: Session,
    *,
    status: JobStatus | None = None,
    plataforma: Plataforma | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Job]]:
    filtros = []
    if status is not None:
        filtros.append(Job.status == status.value)
    if plataforma is not None:
        filtros.append(Job.plataforma == plataforma.value)

    total = db.execute(
        select(func.count()).select_from(Job).where(*filtros)
    ).scalar_one()

    itens = (
        db.execute(
            select(Job)
            .where(*filtros)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return total, list(itens)


def aplicar_patch(
    db: Session,
    job: Job,
    *,
    status: JobStatus | None = None,
    etapa: Etapa | None = None,
    transcript: str | None = None,
    slides_json=None,
    carousel_url: str | None = None,
    error: str | None = None,
    mensagem: str | None = None,
) -> Job:
    """Aplica o callback do worker e registra a transicao no historico."""
    if etapa is not None:
        job.etapa = etapa.value
    if transcript is not None:
        job.transcript = transcript
    if slides_json is not None:
        job.slides_json = slides_json
    if carousel_url is not None:
        job.carousel_url = carousel_url

    if status is not None:
        job.status = status.value
        if status is JobStatus.concluido:
            # sucesso limpa o erro anterior e fecha o pipeline
            job.error = None
            if etapa is None:
                job.etapa = Etapa.finalizado.value
        elif status is JobStatus.processando and error is None:
            job.error = None

    if error is not None:
        job.error = error
        if status is None:
            job.status = JobStatus.erro.value

    job.updated_at = utcnow()

    registrar_evento(
        db,
        job,
        etapa=Etapa(job.etapa),
        status=JobStatus(job.status),
        mensagem=mensagem or error,
    )
    return job


def preparar_retry(db: Session, job: Job) -> Job:
    """Volta o job para a fila, preservando o historico."""
    job.status = JobStatus.pendente.value
    job.etapa = Etapa.recebido.value
    job.error = None
    job.attempts += 1
    job.updated_at = utcnow()
    registrar_evento(
        db,
        job,
        etapa=Etapa.recebido,
        status=JobStatus.pendente,
        mensagem=f"Reprocessamento solicitado (tentativa {job.attempts}).",
    )
    return job
