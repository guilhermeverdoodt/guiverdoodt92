# Painel de Transcrição e Geração de Carrossel

Cola URLs de Reels/TikTok, o sistema baixa, transcreve e devolve um carrossel
pronto. Implementação da arquitetura descrita em
[`docs/arquitetura.md`](docs/arquitetura.md).

```
Streamlit  ──►  FastAPI  ──webhook──►  n8n  ──►  yt-dlp → ffmpeg → faster-whisper
    ▲              │                    │                              │
    │              ▼                    │                          Groq (slides)
    └──polling──  Postgres  ◄──PATCH────┘                              │
                                                              Claude Design / Canva
```

## Subir em 2 minutos (local, SQLite)

```bash
cd painel-carrossel
make install          # venv + dependências + .env
make api              # http://localhost:8000/docs
make dashboard        # http://localhost:8501   (outro terminal)
```

Sem `N8N_WEBHOOK_URL` configurada os jobs ficam em `pendente` e o histórico
registra o aviso — dá para exercitar a API e o painel inteiros antes do n8n
existir.

## Subir completo (Postgres + n8n)

```bash
cp .env.example .env     # troque API_KEY e WORKER_SECRET
make compose-up
```

| Serviço | URL |
|---|---|
| API (docs) | http://localhost:8000/docs |
| Dashboard | http://localhost:8501 |
| n8n | http://localhost:5678 |

Depois importe `n8n/workflow-transcricao-carrossel.json` no n8n, ative o
workflow e aponte `N8N_WEBHOOK_URL` para
`http://n8n:5678/webhook/painel-carrossel`. Detalhes em
[`n8n/README.md`](n8n/README.md).

## API

Autenticação: `X-API-Key` nas rotas do painel, `X-Worker-Secret` no callback
do worker. Chaves separadas de propósito — se a do painel vazar, o worker
continua fechado.

| Método | Rota | O que faz |
|---|---|---|
| `POST` | `/jobs` | Cria um job por URL (`{"url": "..."}` ou `{"urls": [...]}`) e dispara o n8n. |
| `GET` | `/jobs` | Lista com filtros `status`, `plataforma`, `limit`, `offset`. |
| `GET` | `/jobs/stats` | Contagem por status (cards do painel). |
| `GET` | `/jobs/{id}` | Detalhe: transcript, slides, carrossel e **histórico de etapas**. |
| `POST` | `/jobs/{id}/retry` | Recoloca na fila. Bloqueado enquanto processa e acima de `MAX_ATTEMPTS`. |
| `PATCH` | `/jobs/{id}` | Callback do n8n (`X-Worker-Secret`). |
| `GET` | `/healthz` | Probe, sem autenticação. |

```bash
curl -X POST localhost:8000/jobs \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"urls":["https://www.instagram.com/reel/XXXXXXXXXXX/"]}'
```

URL inválida no meio de um lote não derruba o resto: volta em `rejeitados`
com o motivo. Só Instagram e TikTok são aceitos — qualquer outro host é
rejeitado na entrada em vez de virar um job que morre no download.

## Contrato com o worker

A API envia:

```json
{ "job_id": "...", "url": "...", "plataforma": "tiktok",
  "attempts": 0, "callback_url": "http://api:8000/jobs/<id>" }
```

assinado em `X-Signature: sha256=<hmac do corpo>`. O worker responde com
`PATCH callback_url` a cada etapa:

```json
{ "status": "processando", "etapa": "transcricao", "transcript": "...",
  "slides_json": {...}, "carousel_url": "...", "error": null, "mensagem": "..." }
```

Todo PATCH grava uma linha em `job_events` — é o histórico que o painel mostra
e o que responde "qual etapa quebrou" quando o `yt-dlp` cai.

## Ciclo de vida

```
pendente ──► processando ──► concluido
    ▲              │
    └── retry ──── └──► erro   (com a etapa e a mensagem preservadas)
```

Etapas: `recebido → dispatch → download → audio → transcricao → slides →
carrossel → finalizado`.

## Estrutura

```
app/            API FastAPI
  config.py     settings via .env
  models.py     jobs + job_events (SQLAlchemy 2.0)
  crud.py       operações de banco
  platforms.py  validação de URL Instagram/TikTok
  n8n.py        disparo do webhook + assinatura HMAC
  security.py   API key e segredo do worker
  routers/      rotas
dashboard/      painel Streamlit
n8n/            workflow importável
migrations/     schema SQL para Supabase/Neon
scripts/        transcrever.py (faster-whisper, chamado pelo n8n)
tests/          pytest
```

## Configuração

Tudo por variável de ambiente — veja [`.env.example`](.env.example).
Os que importam: `DATABASE_URL`, `API_KEY`, `WORKER_SECRET`,
`N8N_WEBHOOK_URL`, `API_BASE_URL` (usado para montar o `callback_url`).

## Testes

```bash
make test        # 38 testes
```

Cobrem validação de URL, autenticação nos dois níveis, criação em lote,
filtros, o fluxo completo de PATCH, as regras de retry e o comportamento
quando o n8n está fora do ar.

## Pontos de atenção herdados da arquitetura

- **`yt-dlp` vai quebrar.** Instagram e TikTok mudam anti-bot com frequência.
  Por isso a etapa que falhou fica gravada no job e em `job_events`, e o retry
  é um botão no painel. Mantenha o `yt-dlp` atualizado na imagem do worker.
- **Transcrição em CPU é lenta.** `scripts/transcrever.py` está isolado justamente
  para virar um serviço com GPU quando o volume pedir — basta trocar o comando
  do nó no n8n.
- **O webhook é assinado.** Sem HMAC, o endpoint do n8n ficaria aberto para
  qualquer um enfileirar trabalho.
- **Quando o n8n virar gargalo**, troque por Celery/ARQ: o contrato é só o
  webhook de ida e o PATCH de volta; API e dashboard não mudam.
