"""Cliente HTTP fino para a API do painel."""
from __future__ import annotations

from typing import Any

import httpx


class APIError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class PainelAPI:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout

    def _request(self, metodo: str, caminho: str, **kwargs) -> Any:
        url = f"{self.base_url}{caminho}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resposta = client.request(metodo, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            # Normaliza falha de transporte (API fora do ar, timeout, DNS) em
            # APIError, para o painel mostrar um aviso em vez de um traceback.
            raise APIError(0, f"API inacessivel: {exc}") from exc
        if resposta.status_code >= 400:
            try:
                detalhe = resposta.json().get("detail", resposta.text)
            except Exception:
                detalhe = resposta.text
            raise APIError(resposta.status_code, detalhe)
        return resposta.json()

    # --- rotas ---

    def health(self) -> dict:
        return self._request("GET", "/healthz")

    def criar_jobs(self, urls: list[str]) -> dict:
        return self._request("POST", "/jobs", json={"urls": urls})

    def listar_jobs(
        self,
        *,
        status: str | None = None,
        plataforma: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if plataforma:
            params["plataforma"] = plataforma
        return self._request("GET", "/jobs", params=params)

    def detalhar_job(self, job_id: str) -> dict:
        return self._request("GET", f"/jobs/{job_id}")

    def stats(self) -> dict:
        return self._request("GET", "/jobs/stats")

    def reprocessar(self, job_id: str) -> dict:
        return self._request("POST", f"/jobs/{job_id}/retry")
