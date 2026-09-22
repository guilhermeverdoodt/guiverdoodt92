"""Autenticacao: API key para o painel, segredo compartilhado para o worker."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings

API_KEY_HEADER = "X-API-Key"
WORKER_SECRET_HEADER = "X-Worker-Secret"
SIGNATURE_HEADER = "X-Signature"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protege as rotas do painel. Comparacao em tempo constante."""
    settings = get_settings()
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise _unauthorized("API key ausente ou invalida")


def require_worker_secret(x_worker_secret: str | None = Header(default=None)) -> None:
    """Protege o callback PATCH /jobs/{id}, chamado pelo n8n.

    Segredo separado da API key: se a key do painel vazar, o worker continua
    fechado, e vice-versa.
    """
    settings = get_settings()
    if not x_worker_secret or not hmac.compare_digest(
        x_worker_secret, settings.worker_secret
    ):
        raise _unauthorized("Segredo do worker ausente ou invalido")


def assinar_payload(corpo: bytes) -> str:
    """HMAC-SHA256 do corpo do webhook, para o n8n validar a origem."""
    settings = get_settings()
    digest = hmac.new(
        settings.worker_secret.encode("utf-8"), corpo, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"
