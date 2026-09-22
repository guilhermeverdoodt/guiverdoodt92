"""Configuracao da aplicacao, lida do ambiente (.env)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valores que so existem em exemplo/documentacao — nunca podem virar credencial.
PLACEHOLDERS = {
    "dev-api-key",
    "dev-worker-secret",
    "troque-esta-chave",
    "troque-este-segredo",
    "changeme",
    "change-me",
    "secret",
    "password",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Banco ---
    # Postgres em producao (Supabase/Neon). SQLite serve para dev/testes.
    database_url: str = "sqlite:///./painel.db"

    # --- Autenticacao ---
    # Sem valor padrao de proposito: um default previsivel deixaria as rotas
    # autenticadas abertas em qualquer deploy que esquecesse o .env.
    # Chave usada pelo dashboard / consumidores da API (header X-API-Key).
    api_key: str
    # Segredo compartilhado com o n8n: usado nos dois sentidos.
    #  - a API assina o webhook de saida com ele;
    #  - o n8n devolve o mesmo valor no PATCH /jobs/{id}.
    worker_secret: str

    # --- n8n ---
    n8n_webhook_url: str = ""
    n8n_timeout_seconds: float = 10.0

    # --- Regras de negocio ---
    max_urls_per_request: int = 20
    max_attempts: int = 3

    # --- Dashboard ---
    api_base_url: str = "http://localhost:8000"

    @field_validator("api_key", "worker_secret")
    @classmethod
    def _segredo_utilizavel(cls, valor: str, info) -> str:
        limpo = valor.strip()
        if limpo.lower() in PLACEHOLDERS:
            raise ValueError(
                f"{info.field_name.upper()} esta com um valor de exemplo. "
                "Gere um proprio: openssl rand -hex 32"
            )
        if len(limpo) < 8:
            raise ValueError(
                f"{info.field_name.upper()} precisa de ao menos 8 caracteres. "
                "Gere um proprio: openssl rand -hex 32"
            )
        return limpo


@lru_cache
def get_settings() -> Settings:
    return Settings()
