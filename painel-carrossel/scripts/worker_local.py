#!/usr/bin/env python3
"""Worker local — substitui o n8n para testar o fluxo real sem orquestrador.

Fala exatamente o mesmo contrato do workflow do n8n:

    recebe  POST /webhook  {job_id, url, plataforma, attempts, callback_url}
            com X-Signature: sha256=<hmac do corpo>
    devolve PATCH callback_url  com X-Worker-Secret e o campo `attempt`

Responde 200 na hora e processa numa thread, como o n8n com
responseMode=onReceived — assim o POST da API nao fica preso no pipeline.

    python3 scripts/worker_local.py            # escuta em :9000
    python3 scripts/worker_local.py --port 9100 --keep-files

Depois aponte a API para ele:

    N8N_WEBHOOK_URL=http://localhost:9000/webhook

Precisa de: yt-dlp, ffmpeg e faster-whisper no PATH/ambiente.
GROQ_API_KEY e opcional — sem ela a etapa de slides e pulada e o job
termina com a transcricao.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
)
log = logging.getLogger("worker")

PROMPT_SLIDES = (
    "Voce transforma a transcricao de um video curto (Reels/TikTok) em um "
    "carrossel para Instagram. Responda SOMENTE com JSON valido no formato: "
    '{"titulo": "gancho curto para o slide 1", "slides": [{"n": 1, '
    '"titulo": "...", "texto": "ate 220 caracteres"}], "cta": "chamada final", '
    '"legenda": "legenda do post", "hashtags": ["#..."]}. Gere entre 5 e 8 '
    "slides, em portugues do Brasil, mantendo o tom e os argumentos do video. "
    "Nao invente dados."
)


class Etapa:
    DOWNLOAD = "download"
    AUDIO = "audio"
    TRANSCRICAO = "transcricao"
    SLIDES = "slides"
    CARROSSEL = "carrossel"


class EtapaFalhou(Exception):
    """Falha atribuida a uma etapa do pipeline."""

    def __init__(self, etapa: str, mensagem: str):
        self.etapa = etapa
        super().__init__(mensagem)


# --------------------------------------------------------------------------- #
# Configuracao
# --------------------------------------------------------------------------- #
class Config:
    def __init__(self) -> None:
        self.worker_secret = os.getenv("WORKER_SECRET", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.carrossel_url = os.getenv("CARROSSEL_WEBHOOK_URL", "")
        self.carrossel_token = os.getenv("CARROSSEL_API_TOKEN", "")
        self.work_dir = Path(os.getenv("WORKER_WORK_DIR", "/tmp/painel-jobs"))

    def validar(self) -> list[str]:
        problemas = []
        if not self.worker_secret:
            problemas.append("WORKER_SECRET nao definido (precisa ser o mesmo da API).")
        for ferramenta in ("yt-dlp", "ffmpeg"):
            if not shutil.which(ferramenta):
                problemas.append(f"{ferramenta} nao encontrado no PATH.")
        return problemas


# --------------------------------------------------------------------------- #
# Assinatura
# --------------------------------------------------------------------------- #
def assinatura_confere(corpo: bytes, recebida: str, segredo: str) -> bool:
    """Mesma checagem do Code node 'Validar assinatura' no n8n."""
    if not recebida or not segredo:
        return False
    esperada = "sha256=" + hmac.new(
        segredo.encode("utf-8"), corpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(recebida, esperada)


# --------------------------------------------------------------------------- #
# Cliente da API
# --------------------------------------------------------------------------- #
class Painel:
    def __init__(self, callback_url: str, attempt: int, segredo: str):
        self.callback_url = callback_url
        self.attempt = attempt
        self._headers = {"X-Worker-Secret": segredo}

    def patch(self, **campos) -> None:
        corpo = {"attempt": self.attempt, **campos}
        try:
            with httpx.Client(timeout=20.0) as client:
                resposta = client.patch(
                    self.callback_url, json=corpo, headers=self._headers
                )
            if resposta.status_code == 409:
                # retry em andamento: esta execucao ficou obsoleta
                log.warning("callback recusado (409): %s", resposta.text)
            elif resposta.status_code >= 400:
                log.error("PATCH falhou %s: %s", resposta.status_code, resposta.text)
        except httpx.HTTPError as exc:
            log.error("PATCH inacessivel: %s", exc)


# --------------------------------------------------------------------------- #
# Etapas do pipeline
# --------------------------------------------------------------------------- #
def _rodar(cmd: list[str], etapa: str, timeout: int = 900) -> str:
    """Executa um comando como lista de argumentos.

    Sempre sem shell (`shell=False`, o padrao): os argumentos vao direto para
    execve, entao metacaractere de shell em uma URL e literal, nao comando.
    O que ainda seria possivel e injecao de *argumento* — uma URL comecando
    com `-` virar opcao do yt-dlp — e por isso `baixar_video` valida o
    esquema e passa `--` antes do posicional.
    """
    log.info("[%s] %s", etapa, " ".join(cmd[:4]) + (" ..." if len(cmd) > 4 else ""))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise EtapaFalhou(etapa, f"timeout apos {timeout}s") from None
    except FileNotFoundError as exc:
        raise EtapaFalhou(etapa, f"comando nao encontrado: {exc}") from exc

    if proc.returncode != 0:
        detalhe = (proc.stderr or proc.stdout or "").strip()[-1500:]
        raise EtapaFalhou(etapa, f"saiu com codigo {proc.returncode}: {detalhe}")
    return proc.stdout


def url_segura(url: str) -> bool:
    """So http(s). Barra `-opcao`, `file://` e afins antes de virar argumento."""
    return url.startswith(("http://", "https://"))


def baixar_video(url: str, destino: Path) -> Path:
    if not url_segura(url):
        raise EtapaFalhou(Etapa.DOWNLOAD, f"URL recusada pelo worker: {url[:120]!r}")

    destino.mkdir(parents=True, exist_ok=True)
    _rodar(
        [
            "yt-dlp",
            "--no-playlist",
            "--no-progress",
            "--no-warnings",
            "-o",
            str(destino / "video.%(ext)s"),
            # `--` encerra as opcoes: o que vem depois e sempre posicional,
            # mesmo que comece com hifen.
            "--",
            url,
        ],
        Etapa.DOWNLOAD,
    )
    arquivos = sorted(destino.glob("video.*"))
    if not arquivos:
        raise EtapaFalhou(Etapa.DOWNLOAD, "yt-dlp terminou sem gerar arquivo.")
    return arquivos[0]


def extrair_audio(video: Path) -> Path:
    audio = video.parent / "audio.wav"
    _rodar(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            # absoluto de proposito: um caminho relativo iniciado por hifen
            # seria lido como opcao pelo ffmpeg
            "-i", str(video.resolve()),
            "-vn", "-ac", "1", "-ar", "16000",
            str(audio.resolve()),
        ],
        Etapa.AUDIO,
    )
    if not audio.exists():
        raise EtapaFalhou(Etapa.AUDIO, "ffmpeg nao gerou audio.wav")
    return audio


def transcrever(audio: Path) -> dict:
    """Chama o mesmo scripts/transcrever.py que o n8n usa."""
    saida = _rodar(
        [sys.executable, str(RAIZ / "scripts" / "transcrever.py"), str(audio)],
        Etapa.TRANSCRICAO,
        timeout=3600,
    )
    try:
        dados = json.loads(saida)
    except json.JSONDecodeError:
        raise EtapaFalhou(
            Etapa.TRANSCRICAO, f"saida nao e JSON: {saida[:500]}"
        ) from None
    if dados.get("error"):
        raise EtapaFalhou(Etapa.TRANSCRICAO, dados["error"])
    if not (dados.get("text") or "").strip():
        raise EtapaFalhou(
            Etapa.TRANSCRICAO, "transcricao vazia — video sem fala ou audio corrompido."
        )
    return dados


def estruturar_slides(texto: str, cfg: Config) -> dict:
    resposta = None
    try:
        with httpx.Client(timeout=90.0) as client:
            resposta = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {cfg.groq_api_key}"},
                json={
                    "model": cfg.groq_model,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": PROMPT_SLIDES},
                        {"role": "user", "content": texto},
                    ],
                },
            )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        detalhe = resposta.text[:500] if resposta is not None else str(exc)
        raise EtapaFalhou(Etapa.SLIDES, f"Groq: {detalhe}") from exc

    return validar_slides(resposta.json())


def validar_slides(corpo: dict) -> dict:
    """Extrai e valida o JSON de slides da resposta estilo OpenAI."""
    try:
        bruto = corpo["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise EtapaFalhou(
            Etapa.SLIDES, f"resposta sem conteudo: {json.dumps(corpo)[:500]}"
        ) from None

    try:
        slides = json.loads(bruto) if isinstance(bruto, str) else bruto
    except json.JSONDecodeError:
        raise EtapaFalhou(
            Etapa.SLIDES, f"slides nao vieram em JSON: {str(bruto)[:500]}"
        ) from None

    if not isinstance(slides.get("slides"), list) or not slides["slides"]:
        raise EtapaFalhou(Etapa.SLIDES, 'estrutura invalida: falta o array "slides".')
    return slides


def gerar_carrossel(job_id: str, slides: dict, cfg: Config) -> str | None:
    """POST no endpoint de carrossel (Claude Design MCP / Canva / o seu)."""
    if not cfg.carrossel_url:
        return None

    headers = {}
    if cfg.carrossel_token:
        headers["Authorization"] = f"Bearer {cfg.carrossel_token}"
    resposta = None
    try:
        with httpx.Client(timeout=180.0) as client:
            resposta = client.post(
                cfg.carrossel_url,
                headers=headers,
                json={"job_id": job_id, "slides": slides},
            )
        resposta.raise_for_status()
        corpo = resposta.json()
    except httpx.HTTPError as exc:
        detalhe = resposta.text[:500] if resposta is not None else str(exc)
        raise EtapaFalhou(Etapa.CARROSSEL, f"endpoint de carrossel: {detalhe}") from exc
    except json.JSONDecodeError:
        raise EtapaFalhou(Etapa.CARROSSEL, "resposta nao e JSON") from None

    url = corpo.get("carousel_url") or corpo.get("url")
    if not url:
        raise EtapaFalhou(
            Etapa.CARROSSEL, f"resposta sem carousel_url: {json.dumps(corpo)[:300]}"
        )
    return url


# --------------------------------------------------------------------------- #
# Orquestracao (o que o n8n faz no workflow)
# --------------------------------------------------------------------------- #
def processar(payload: dict, cfg: Config, manter_arquivos: bool) -> None:
    job_id = payload["job_id"]
    painel = Painel(payload["callback_url"], payload.get("attempts", 0), cfg.worker_secret)
    pasta = cfg.work_dir / job_id

    try:
        painel.patch(
            status="processando", etapa=Etapa.DOWNLOAD, mensagem="worker local assumiu"
        )
        video = baixar_video(payload["url"], pasta)

        painel.patch(etapa=Etapa.AUDIO, mensagem=f"baixado: {video.name}")
        audio = extrair_audio(video)

        painel.patch(etapa=Etapa.TRANSCRICAO, mensagem="audio extraido")
        transcricao = transcrever(audio)
        texto = transcricao["text"]

        if not cfg.groq_api_key:
            painel.patch(
                status="concluido",
                etapa=Etapa.TRANSCRICAO,
                transcript=texto,
                mensagem="GROQ_API_KEY ausente — parou na transcricao.",
            )
            log.info("job %s concluido so com transcricao (sem GROQ_API_KEY)", job_id)
            return

        painel.patch(
            etapa=Etapa.SLIDES,
            transcript=texto,
            mensagem=f"transcricao ok ({len(texto)} caracteres)",
        )
        slides = estruturar_slides(texto, cfg)

        painel.patch(
            etapa=Etapa.CARROSSEL, slides_json=slides, mensagem="slides estruturados"
        )
        carousel_url = gerar_carrossel(job_id, slides, cfg)

        painel.patch(
            status="concluido",
            etapa=Etapa.CARROSSEL,
            carousel_url=carousel_url,
            mensagem=(
                "carrossel gerado"
                if carousel_url
                else "CARROSSEL_WEBHOOK_URL ausente — parou nos slides."
            ),
        )
        log.info("job %s concluido", job_id)

    except EtapaFalhou as falha:
        log.error("job %s falhou em %s: %s", job_id, falha.etapa, falha)
        painel.patch(status="erro", etapa=falha.etapa, error=str(falha))
    except Exception as exc:  # falha inesperada nao pode deixar o job preso
        log.exception("job %s: erro inesperado", job_id)
        painel.patch(status="erro", error=f"worker local: {exc}")
    finally:
        if not manter_arquivos:
            shutil.rmtree(pasta, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Servidor HTTP
# --------------------------------------------------------------------------- #
def criar_handler(cfg: Config, manter_arquivos: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, formato, *args):  # silencia o log padrao
            log.debug(formato, *args)

        def _responder(self, codigo: int, corpo: dict) -> None:
            dados = json.dumps(corpo).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                self._responder(200, {"status": "ok"})
            else:
                self._responder(404, {"erro": "use POST /webhook"})

        def do_POST(self):  # noqa: N802
            tamanho = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(tamanho)

            if not assinatura_confere(
                corpo, self.headers.get("X-Signature", ""), cfg.worker_secret
            ):
                log.warning("assinatura invalida de %s", self.client_address[0])
                self._responder(401, {"erro": "assinatura invalida"})
                return

            try:
                payload = json.loads(corpo)
            except json.JSONDecodeError:
                self._responder(400, {"erro": "corpo nao e JSON"})
                return

            faltando = [
                c for c in ("job_id", "url", "callback_url") if not payload.get(c)
            ]
            if faltando:
                self._responder(400, {"erro": f"payload sem {', '.join(faltando)}"})
                return

            # 200 imediato; o pipeline roda em background (igual ao n8n)
            self._responder(200, {"aceito": payload["job_id"]})
            log.info("job %s aceito: %s", payload["job_id"], payload["url"])
            threading.Thread(
                target=processar,
                args=(payload, cfg, manter_arquivos),
                daemon=True,
            ).start()

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker local do painel de carrossel")
    parser.add_argument("--port", type=int, default=int(os.getenv("WORKER_PORT", "9000")))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--keep-files", action="store_true", help="nao apaga os arquivos do job"
    )
    args = parser.parse_args()

    cfg = Config()
    problemas = cfg.validar()
    if problemas:
        for problema in problemas:
            log.error("%s", problema)
        return 1

    if not cfg.groq_api_key:
        log.warning("GROQ_API_KEY ausente: os jobs vao parar na transcricao.")
    if not cfg.carrossel_url:
        log.warning("CARROSSEL_WEBHOOK_URL ausente: os jobs vao parar nos slides.")

    servidor = ThreadingHTTPServer(
        (args.host, args.port), criar_handler(cfg, args.keep_files)
    )
    log.info("worker ouvindo em http://%s:%s/webhook", args.host, args.port)
    log.info("aponte a API com: N8N_WEBHOOK_URL=http://%s:%s/webhook", args.host, args.port)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("encerrando")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
