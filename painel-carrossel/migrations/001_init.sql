-- Painel de Transcricao e Carrossel — schema inicial (Postgres).
-- A API tambem cria essas tabelas via SQLAlchemy no startup; este arquivo
-- serve para aplicar o schema direto no Supabase/Neon.

CREATE TABLE IF NOT EXISTS jobs (
    id            VARCHAR(32) PRIMARY KEY,
    url           TEXT        NOT NULL,
    plataforma    VARCHAR(20) NOT NULL DEFAULT 'desconhecida',
    status        VARCHAR(20) NOT NULL DEFAULT 'pendente',
    etapa         VARCHAR(20) NOT NULL DEFAULT 'recebido',
    transcript    TEXT,
    slides_json   JSONB,
    carousel_url  TEXT,
    error         TEXT,
    attempts      INTEGER     NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT jobs_status_check
        CHECK (status IN ('pendente', 'processando', 'concluido', 'erro')),
    CONSTRAINT jobs_plataforma_check
        CHECK (plataforma IN ('instagram', 'tiktok', 'desconhecida'))
);

CREATE INDEX IF NOT EXISTS ix_jobs_status     ON jobs (status);
CREATE INDEX IF NOT EXISTS ix_jobs_created_at ON jobs (created_at DESC);

-- Historico das etapas: qual passo rodou, quando, e o que aconteceu.
CREATE TABLE IF NOT EXISTS job_events (
    id         VARCHAR(32) PRIMARY KEY,
    job_id     VARCHAR(32) NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    etapa      VARCHAR(20) NOT NULL,
    status     VARCHAR(20) NOT NULL,
    mensagem   TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_job_events_job_id ON job_events (job_id);

-- updated_at automatico (a API tambem seta, isto e a rede de seguranca
-- para updates feitos direto no banco).
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_jobs_updated_at ON jobs;
CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
