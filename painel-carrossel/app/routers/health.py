from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["infra"])


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)) -> dict:
    """Checa processo + banco. Sem autenticacao: serve de probe."""
    try:
        db.execute(text("SELECT 1"))
        banco = "ok"
    except Exception as exc:  # pragma: no cover - depende de falha real
        banco = f"erro: {exc}"
    return {"status": "ok" if banco == "ok" else "degradado", "database": banco}
