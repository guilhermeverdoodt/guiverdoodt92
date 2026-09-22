# Workflow do n8n

`workflow-transcricao-carrossel.json` é o orquestrador do pipeline. Importe em
**Workflows → Import from File**.

## Fluxo

```
Webhook Painel            POST /webhook/painel-carrossel (vindo da API)
  └─ Validar assinatura   confere o HMAC X-Signature
     └─ Marcar processando        PATCH status=processando
        └─ Download (yt-dlp)      baixa o vídeo
           └─ Extrair áudio (ffmpeg)   wav mono 16 kHz
              └─ Transcrever (faster-whisper)  scripts/transcrever.py
                 └─ Salvar transcrição         PATCH transcript
                    └─ Estruturar slides (Groq)  JSON com título/slides/CTA
                       └─ Salvar slides          PATCH slides_json
                          └─ Gerar carrossel     Claude Design MCP / Canva
                             └─ Marcar concluído PATCH status=concluido + carousel_url
                                └─ Limpar arquivos
```

Toda etapa que pode falhar tem **saída de erro** ligada em `Montar erro →
Marcar erro → Limpar após erro`. O nó `Montar erro` usa `$prevNode.name` para
descobrir qual etapa quebrou e manda para a API `status=erro` com a etapa e a
mensagem — é isso que aparece no painel quando o `yt-dlp` quebra por mudança de
layout ou anti-bot.

Os PATCH de progresso (`Marcar processando`, `Marcar áudio`, `Marcar
transcrição`) usam `continueRegularOutput`: se a API piscar, o pipeline segue.
Os que carregam dado de verdade (`Salvar transcrição`, `Salvar slides`,
`Marcar concluído`) vão para o ramo de erro.

## Variáveis de ambiente do n8n

| Variável | Para quê |
|---|---|
| `PAINEL_WORKER_SECRET` | Mesmo valor do `WORKER_SECRET` da API. Valida o HMAC de entrada e assina os PATCH de volta. |
| `GROQ_API_KEY` | Chave da Groq. |
| `GROQ_MODEL` | Opcional. Padrão `llama-3.3-70b-versatile`. |
| `CARROSSEL_WEBHOOK_URL` | Endpoint que recebe os slides e devolve `{"carousel_url": "..."}`. |
| `CARROSSEL_API_TOKEN` | Bearer do endpoint acima. |

O acesso a `$env` dentro dos nós exige `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` no
n8n (já vem assim no `docker-compose.yml` deste repositório).

## Pré-requisitos no container do n8n

Os nós `Execute Command` rodam dentro do n8n, então ele precisa de:

- `yt-dlp` (mantenha atualizado — Instagram e TikTok quebram com frequência)
- `ffmpeg`
- `python3` + `faster-whisper`
- `scripts/transcrever.py` montado em `/opt/painel/scripts/`
- um volume gravável em `/data/jobs`

O `docker-compose.yml` da raiz já monta os dois caminhos. Para a imagem oficial
do n8n, instale as dependências num `Dockerfile` próprio ou use a imagem
`n8n-worker` deste repositório.

## Etapa do carrossel

O nó `Gerar carrossel` é um HTTP Request para `CARROSSEL_WEBHOOK_URL`, de
propósito: ele é o ponto de plug. Três caminhos:

1. **Claude Design MCP / Canva MCP** — aponte para um endpoint seu que fale MCP
   e devolva a URL do design.
2. **Nó MCP Client do n8n** — troque o HTTP Request pelo nó MCP e mantenha o
   resto igual; o importante é o item de saída ter `carousel_url`.
3. **Canva Connect API** — POST direto no autofill de um brand template.

O `Marcar concluído` lê `carousel_url` ou `url` da resposta.

## Trocando o n8n por Celery/ARQ

O contrato é só o webhook: `POST` com `{job_id, url, plataforma, attempts,
callback_url}` assinado em `X-Signature`, e `PATCH callback_url` com
`X-Worker-Secret`. Qualquer worker que respeite isso substitui o n8n sem tocar
na API nem no dashboard.
