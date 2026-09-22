"""Testes das partes puras do worker local (sem rede nem ferramentas externas)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "worker_local", RAIZ / "scripts" / "worker_local.py"
)
worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker)

SEGREDO = "test-worker-secret"


# --------------------------- assinatura --------------------------- #
def test_assinatura_do_worker_bate_com_a_da_api():
    """O worker precisa validar exatamente o que app.security assina."""
    from app.security import assinar_payload

    corpo = json.dumps(
        {"job_id": "abc", "url": "https://x", "callback_url": "http://y"},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    assert worker.assinatura_confere(corpo, assinar_payload(corpo), SEGREDO)


def test_assinatura_rejeita_corpo_adulterado():
    corpo = b'{"job_id":"abc"}'
    assinatura = "sha256=" + __import__("hmac").new(
        SEGREDO.encode(), corpo, __import__("hashlib").sha256
    ).hexdigest()

    assert worker.assinatura_confere(corpo, assinatura, SEGREDO)
    assert not worker.assinatura_confere(b'{"job_id":"xyz"}', assinatura, SEGREDO)


@pytest.mark.parametrize(
    "recebida,segredo", [("", SEGREDO), ("sha256=deadbeef", SEGREDO), ("qualquer", "")]
)
def test_assinatura_invalida(recebida, segredo):
    assert not worker.assinatura_confere(b"{}", recebida, segredo)


# ----------------------------- slides ----------------------------- #
def _resposta_groq(conteudo) -> dict:
    return {"choices": [{"message": {"content": conteudo}}]}


def test_slides_validos():
    slides = worker.validar_slides(
        _resposta_groq(json.dumps({"titulo": "t", "slides": [{"n": 1, "texto": "a"}]}))
    )
    assert slides["slides"][0]["texto"] == "a"


def test_slides_aceita_objeto_ja_decodificado():
    slides = worker.validar_slides(
        _resposta_groq({"titulo": "t", "slides": [{"n": 1, "texto": "a"}]})
    )
    assert slides["titulo"] == "t"


@pytest.mark.parametrize(
    "conteudo,trecho",
    [
        ("nao sou json", "nao vieram em JSON"),
        (json.dumps({"titulo": "t"}), 'falta o array "slides"'),
        (json.dumps({"titulo": "t", "slides": []}), 'falta o array "slides"'),
    ],
)
def test_slides_invalidos(conteudo, trecho):
    with pytest.raises(worker.EtapaFalhou, match=trecho.replace('"', '"')):
        worker.validar_slides(_resposta_groq(conteudo))


def test_resposta_sem_choices():
    with pytest.raises(worker.EtapaFalhou, match="sem conteudo"):
        worker.validar_slides({"error": {"message": "sem creditos"}})


def test_etapa_falhou_carrega_a_etapa():
    erro = worker.EtapaFalhou(worker.Etapa.DOWNLOAD, "yt-dlp: HTTP 403")
    assert erro.etapa == "download"
    assert "403" in str(erro)


# --------------------------- subprocesso --------------------------- #
def test_comando_ausente_vira_etapa_falhou():
    with pytest.raises(worker.EtapaFalhou) as info:
        worker._rodar(["comando-que-nao-existe-xyz"], worker.Etapa.DOWNLOAD)
    assert info.value.etapa == "download"
    assert "nao encontrado" in str(info.value)


def test_codigo_de_saida_nao_zero_vira_etapa_falhou():
    with pytest.raises(worker.EtapaFalhou, match="codigo 3"):
        worker._rodar(["sh", "-c", "echo falhou >&2; exit 3"], worker.Etapa.AUDIO)
