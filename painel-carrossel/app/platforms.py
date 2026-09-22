"""Deteccao da plataforma a partir da URL."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models import Plataforma

_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "instagr.am", "ig.me"}
_TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}

# Instagram: /p/, /reel/, /reels/, /tv/
_INSTAGRAM_PATH = re.compile(r"^/(p|reel|reels|tv)/[\w\-]+", re.IGNORECASE)

# TikTok no dominio principal: so os formatos que identificam um video.
_TIKTOK_PATH = re.compile(r"^/(@[\w.\-]+/(video|photo)/\d+|v/\d+|t/\w+)", re.IGNORECASE)

# Encurtadores (vm./vt./m.) usam um slug opaco: /ZMabcdefg/. So ali o slug
# generico e aceito — no dominio principal ele deixaria passar /explore,
# /foryou e qualquer outro caminho que nao e video.
_TIKTOK_SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com"}
_TIKTOK_SHORT_PATH = re.compile(r"^/[\w\-]{5,}/?$", re.IGNORECASE)


class URLInvalida(ValueError):
    pass


def _host(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise URLInvalida(f"URL invalida: {url!r}")
    return parsed.netloc.lower()


def detectar_plataforma(url: str) -> Plataforma:
    """Retorna a plataforma da URL. Levanta URLInvalida se nao for http(s)."""
    host = _host(url)
    if host in _INSTAGRAM_HOSTS or host.endswith(".instagram.com"):
        return Plataforma.instagram
    if host in _TIKTOK_HOSTS or host.endswith(".tiktok.com"):
        return Plataforma.tiktok
    return Plataforma.desconhecida


def validar_url(url: str) -> tuple[str, Plataforma]:
    """Normaliza a URL e devolve (url, plataforma).

    So aceitamos Instagram e TikTok — o pipeline (yt-dlp + anti-bot) foi
    desenhado para esses dois. Qualquer outro host e rejeitado na entrada,
    em vez de virar um job que falha no download.
    """
    url = url.strip()
    plataforma = detectar_plataforma(url)
    if plataforma is Plataforma.desconhecida:
        raise URLInvalida(
            f"Plataforma nao suportada: {url!r}. Aceitamos Instagram e TikTok."
        )

    parsed = urlparse(url)
    path = parsed.path or "/"
    if plataforma is Plataforma.instagram and not _INSTAGRAM_PATH.match(path):
        raise URLInvalida(
            f"URL do Instagram sem post/reel identificavel: {url!r}"
        )
    if plataforma is Plataforma.tiktok:
        host = parsed.netloc.lower()
        curta = host in _TIKTOK_SHORT_HOSTS and _TIKTOK_SHORT_PATH.match(path)
        if not curta and not _TIKTOK_PATH.match(path):
            raise URLInvalida(f"URL do TikTok sem video identificavel: {url!r}")

    return url, plataforma
