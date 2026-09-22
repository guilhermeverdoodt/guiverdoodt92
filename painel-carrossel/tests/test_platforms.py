from __future__ import annotations

import pytest

from app.models import Plataforma
from app.platforms import URLInvalida, detectar_plataforma, validar_url


@pytest.mark.parametrize(
    "url,esperado",
    [
        ("https://www.instagram.com/reel/Cx1y2z3AbCd/", Plataforma.instagram),
        ("https://instagram.com/p/Cx1y2z3AbCd/", Plataforma.instagram),
        ("https://www.tiktok.com/@user/video/7300000000000000000", Plataforma.tiktok),
        ("https://vm.tiktok.com/ZMabcdefg/", Plataforma.tiktok),
        ("https://youtube.com/watch?v=abc", Plataforma.desconhecida),
    ],
)
def test_detecta_plataforma(url, esperado):
    assert detectar_plataforma(url) is esperado


@pytest.mark.parametrize(
    "url",
    [
        "instagram.com/reel/abc",  # sem esquema
        "ftp://instagram.com/reel/abc",
        "nao-e-url",
    ],
)
def test_url_malformada(url):
    with pytest.raises(URLInvalida):
        validar_url(url)


def test_plataforma_nao_suportada():
    with pytest.raises(URLInvalida, match="nao suportada"):
        validar_url("https://www.youtube.com/watch?v=abc")


def test_instagram_sem_post():
    with pytest.raises(URLInvalida, match="sem post"):
        validar_url("https://www.instagram.com/usuario/")


def test_validar_normaliza_espacos():
    url, plataforma = validar_url("  https://www.instagram.com/reel/Cx1y2z3AbCd/  ")
    assert url == "https://www.instagram.com/reel/Cx1y2z3AbCd/"
    assert plataforma is Plataforma.instagram


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/explore",
        "https://www.tiktok.com/foryou",
        "https://www.tiktok.com/@usuario",
    ],
)
def test_tiktok_sem_video_e_rejeitado(url):
    """O slug generico so vale para encurtador; no dominio principal, nao."""
    with pytest.raises(URLInvalida, match="sem video"):
        validar_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://vm.tiktok.com/ZMabcdefg/",
        "https://vt.tiktok.com/ZSxyzwvut",
        "https://www.tiktok.com/@usuario/video/7300000000000000000",
        "https://www.tiktok.com/t/ZTabc123/",
    ],
)
def test_tiktok_formatos_validos(url):
    assert validar_url(url)[1] is Plataforma.tiktok
