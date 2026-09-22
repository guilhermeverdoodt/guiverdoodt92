#!/usr/bin/env python3
"""Transcreve um audio com faster-whisper e imprime JSON no stdout.

Usado pelo n8n (Execute Command) para manter a etapa de transcricao isolada:
se um dia ela migrar para GPU ou para um servico separado, so este arquivo muda.

    python3 scripts/transcrever.py /data/jobs/<id>/audio.wav [--modelo small]

Saida:
    {"text": "...", "language": "pt", "duration": 91.3, "segments": [...]}
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcricao com faster-whisper")
    parser.add_argument("audio", help="caminho do arquivo de audio")
    parser.add_argument(
        "--modelo",
        default=os.getenv("WHISPER_MODEL", "small"),
        help="tamanho do modelo (tiny/base/small/medium/large-v3)",
    )
    parser.add_argument(
        "--device", default=os.getenv("WHISPER_DEVICE", "cpu"), help="cpu ou cuda"
    )
    parser.add_argument(
        "--compute-type",
        default=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        help="int8 (CPU) ou float16 (GPU)",
    )
    parser.add_argument("--idioma", default=os.getenv("WHISPER_LANGUAGE", "pt"))
    args = parser.parse_args()

    if not os.path.isfile(args.audio):
        print(json.dumps({"error": f"audio nao encontrado: {args.audio}"}))
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            json.dumps(
                {"error": "faster-whisper nao instalado (pip install faster-whisper)"}
            )
        )
        return 1

    modelo = WhisperModel(args.modelo, device=args.device, compute_type=args.compute_type)
    segmentos, info = modelo.transcribe(args.audio, language=args.idioma, vad_filter=True)

    lista = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segmentos
    ]
    texto = " ".join(s["text"] for s in lista).strip()

    json.dump(
        {
            "text": texto,
            "language": info.language,
            "duration": round(info.duration, 2),
            "segments": lista,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
