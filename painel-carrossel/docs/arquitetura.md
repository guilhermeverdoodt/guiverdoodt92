# Arquitetura — Painel de Transcrição e Geração de Carrossel

Painel simples para inserir vídeos do Instagram/TikTok, transcrever automaticamente e gerar carrosséis via Claude Design MCP.

## 1. Interface (dashboard)

Começar com **Streamlit** — Python puro, roda no mesmo processo do backend, MVP funcional em horas.

Se o projeto virar produto pra terceiros, migrar para **Next.js + Tailwind** consumindo a mesma API.

## 2. API (FastAPI)

Endpoints mínimos:

```
POST   /jobs           -> recebe URL(s) do Instagram/TikTok, cria o job
GET    /jobs           -> lista jobs e status
GET    /jobs/{id}      -> detalhe: status, transcript, slides, link do carrossel
POST   /jobs/{id}/retry
PATCH  /jobs/{id}       (callback interno do worker/n8n atualizando o job)
```

Autenticação simples (API key ou login básico) já resolve — é painel interno.

## 3. Processamento assíncrono

Download + transcrição + geração do carrossel demora — não pode ser síncrono na request HTTP.

Reaproveitar o **n8n** como orquestrador:

```
FastAPI grava o job (status: pendente)
   -> dispara webhook pro n8n
      -> n8n roda: yt-dlp -> ffmpeg -> faster-whisper -> Groq (estrutura em slides) -> Canva MCP (gera o carrossel)
         -> n8n faz PATCH /jobs/{id} no final (sucesso ou erro)
Dashboard consulta GET /jobs/{id} em polling e mostra o resultado
```

Isso evita reescrever fila/orquestração do zero. Se o volume crescer e o n8n virar gargalo, migrar para Celery/Redis ou ARQ com workers Python dedicados.

## 4. Dados

**Postgres** (Supabase/Neon):

```sql
jobs (
  id, url, plataforma, status,
  transcript, slides_json, carousel_url,
  error, created_at, updated_at
)
```

Arquivos (vídeo/áudio temporário, output do Canva): **Supabase Storage**.

## 5. Pipeline de processamento (dentro do n8n)

1. **Download**: `yt-dlp` — baixa o vídeo do Instagram/TikTok
2. **Extração de áudio**: `ffmpeg`
3. **Transcrição**: `faster-whisper` (local, MIT license)
4. **Estruturação em slides**: LLM via Groq — transforma a transcrição em N slides + título + CTA
5. **Geração visual**: Claude Design MCP — renderiza o carrossel a partir dos slides estruturados

## 6. Pontos de atenção

- Instagram e TikTok mudam layout/proteção anti-bot com frequência — `yt-dlp` vai quebrar de vez em quando. Manter status `erro` com log da etapa que falhou é essencial.
- Se o volume de vídeo crescer, transcrição em CPU fica lenta — isolar essa etapa e considerar GPU quando fizer sentido.
- Webhook entre FastAPI e n8n precisa de um secret simples para não virar endpoint aberto.
