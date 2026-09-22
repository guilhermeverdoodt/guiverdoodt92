"""Configuracao da aplicacao, lida do ambiente (.env)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Banco ---
    # Postgres em producao (Supabase/Neon). SQLite serve para dev/testes.
    database_url: str = "sqlite:///./painel.db"

    # --- Autenticacao ---
    # Chave usada pelo dashboard / consumidores da API (header X-API-Key).
    api_key: str = "dev-api-key"
    # Segredo compartilhado com o n8n: usado nos dois sentidos.
    #  - a API assina o webhook de saida com ele;
    #  - o n8n devolve o mesmo valor no PATCH /jobs/{id}.
    worker_secret: str = "dev-worker-secret"

    # --- n8n ---
    n8n_webhook_url: str = ""
    n8n_timeout_seconds: float = 10.0

    # --- Regras de negocio ---
    max_urls_per_request: int = 20
    max_attempts: int = 3

    # --- Dashboard ---
    api_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
