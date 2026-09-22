"""Rotas de jobs: criacao, consulta, retry e callback do worker."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import crud
from app.config import get_settings
from app.db import get_db
from app.models import Job, JobStatus, Plataforma
from app.n8n import disparar_job_por_id
from app.platforms import URLInvalida, validar_url
from app.schemas import (
    JobCreate,
    JobCreateOut,
    JobDetailOut,
    JobListOut,
    JobOut,
    JobPatch,
)
from app.security import require_api_key, require_worker_secret

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobCreateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def criar_jobs(
    payload: JobCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreateOut:
    """Cria um job por URL e dispara o n8n em background.

    URLs invalidas nao derrubam o lote: voltam em `rejeitados`.
    """
    settings = get_settings()
    urls = payload.todas_urls()

    if len(urls) > settings.max_urls_per_request:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximo de {settings.max_urls_per_request} URLs por requisicao.",
        )

    criados: list[Job] = []
    rejeitados: list[dict[str, str]] = []

    for bruta in urls:
        try:
            url, plataforma = validar_url(bruta)
        except URLInvalida as exc:
            rejeitados.append({"url": bruta, "motivo": str(exc)})
            continue
        criados.append(crud.criar_job(db, url=url, plataforma=plataforma))

    if not criados and rejeitados:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"rejeitados": rejeitados},
        )

    db.commit()
    for job in criados:
        db.refresh(job)
        background.add_task(disparar_job_por_id, job.id)

    return JobCreateOut(
        criados=[JobOut.model_validate(job) for job in criados],
        rejeitados=rejeitados,
    )


@router.get("", response_model=JobListOut, dependencies=[Depends(require_api_key)])
def listar_jobs(
    status_filtro: JobStatus | None = Query(default=None, alias="status"),
    plataforma: Plataforma | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> JobListOut:
    total, itens = crud.listar_jobs(
        db, status=status_filtro, plataforma=plataforma, limit=limit, offset=offset
    )
    return JobListOut(total=total, items=[JobOut.model_validate(j) for j in itens])


@router.get("/stats", dependencies=[Depends(require_api_key)])
def estatisticas(db: Session = Depends(get_db)) -> dict[str, int]:
    """Contagem por status — alimenta os cards do dashboard."""
    linhas = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    contagem = {s.value: 0 for s in JobStatus}
    for nome, quantidade in linhas:
        contagem[nome] = quantidade
    contagem["total"] = sum(contagem.values())
    return contagem


@router.get(
    "/{job_id}", response_model=JobDetailOut, dependencies=[Depends(require_api_key)]
)
def detalhar_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    job = crud.buscar_job(db, job_id, com_eventos=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nao encontrado")
    return JobDetailOut.model_validate(job)


@router.post(
    "/{job_id}/retry",
    response_model=JobOut,
    dependencies=[Depends(require_api_key)],
)
def reprocessar_job(
    job_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobOut:
    settings = get_settings()
    job = crud.buscar_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nao encontrado")

    if JobStatus(job.status) not in crud.STATUS_REPROCESSAVEIS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job em '{job.status}' — aguarde terminar antes de reprocessar.",
        )
    if job.attempts >= settings.max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Limite de {settings.max_attempts} tentativas atingido.",
        )

    crud.preparar_retry(db, job)
    db.commit()
    db.refresh(job)
    background.add_task(disparar_job_por_id, job.id)
    return JobOut.model_validate(job)


@router.patch(
    "/{job_id}",
    response_model=JobOut,
    dependencies=[Depends(require_worker_secret)],
)
def atualizar_job(
    job_id: str, payload: JobPatch, db: Session = Depends(get_db)
) -> JobOut:
    """Callback interno do n8n: avanca a etapa ou fecha o job."""
    job = crud.buscar_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nao encontrado")

    crud.aplicar_patch(
        db,
        job,
        status=payload.status,
        etapa=payload.etapa,
        transcript=payload.transcript,
        slides_json=payload.slides_json,
        carousel_url=payload.carousel_url,
        error=payload.error,
        mensagem=payload.mensagem,
    )
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)
