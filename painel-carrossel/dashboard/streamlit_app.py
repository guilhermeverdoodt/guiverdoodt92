"""Painel de Transcricao e Geracao de Carrossel — dashboard Streamlit.

Roda com:  streamlit run dashboard/streamlit_app.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.api_client import APIError, PainelAPI  # noqa: E402

ICONE_STATUS = {
    "pendente": "🕓",
    "processando": "⚙️",
    "concluido": "✅",
    "erro": "❌",
}

st.set_page_config(
    page_title="Painel de Carrossel", page_icon="🎠", layout="wide"
)


# --------------------------------------------------------------------------- #
# Sidebar: conexao
# --------------------------------------------------------------------------- #
def sidebar() -> PainelAPI:
    st.sidebar.header("Conexao")
    base_url = st.sidebar.text_input(
        "API", value=os.getenv("API_BASE_URL", "http://localhost:8000")
    )
    api_key = st.sidebar.text_input(
        "API key", value=os.getenv("API_KEY", ""), type="password"
    )
    api = PainelAPI(base_url, api_key)

    try:
        saude = api.health()
        st.sidebar.success(f"API online — banco: {saude['database']}")
    except Exception as exc:
        st.sidebar.error(f"API inacessivel: {exc}")

    st.sidebar.divider()
    st.session_state["auto_refresh"] = st.sidebar.checkbox(
        "Atualizar a cada 5s", value=st.session_state.get("auto_refresh", False)
    )
    if st.sidebar.button("Atualizar agora", width="stretch"):
        st.rerun()
    return api


# --------------------------------------------------------------------------- #
# Envio de URLs
# --------------------------------------------------------------------------- #
def bloco_envio(api: PainelAPI) -> None:
    st.subheader("Novo job")
    with st.form("form_urls", clear_on_submit=True):
        texto = st.text_area(
            "URLs do Instagram / TikTok (uma por linha)",
            placeholder=(
                "https://www.instagram.com/reel/XXXXXXXXXXX/\n"
                "https://www.tiktok.com/@usuario/video/7300000000000000000"
            ),
            height=110,
        )
        enviado = st.form_submit_button("Transcrever e gerar carrossel", type="primary")

    if not enviado:
        return

    urls = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if not urls:
        st.warning("Cole pelo menos uma URL.")
        return

    try:
        resultado = api.criar_jobs(urls)
    except APIError as exc:
        st.error(f"Falha ao criar os jobs: {exc.detail}")
        return

    criados = resultado.get("criados", [])
    rejeitados = resultado.get("rejeitados", [])
    if criados:
        st.success(f"{len(criados)} job(s) na fila.")
    for item in rejeitados:
        st.warning(f"{item['url']} — {item['motivo']}")


# --------------------------------------------------------------------------- #
# Metricas + lista
# --------------------------------------------------------------------------- #
def bloco_metricas(api: PainelAPI) -> None:
    try:
        stats = api.stats()
    except APIError as exc:
        st.error(f"Nao consegui ler as estatisticas: {exc.detail}")
        return

    colunas = st.columns(5)
    colunas[0].metric("Total", stats.get("total", 0))
    for coluna, chave in zip(colunas[1:], ["pendente", "processando", "concluido", "erro"]):
        coluna.metric(f"{ICONE_STATUS[chave]} {chave.capitalize()}", stats.get(chave, 0))


def bloco_lista(api: PainelAPI) -> list[dict]:
    st.subheader("Jobs")
    filtro_status, filtro_plataforma, filtro_limite = st.columns([1, 1, 1])
    status = filtro_status.selectbox(
        "Status", ["todos", "pendente", "processando", "concluido", "erro"]
    )
    plataforma = filtro_plataforma.selectbox(
        "Plataforma", ["todas", "instagram", "tiktok"]
    )
    limite = filtro_limite.slider("Quantidade", 10, 200, 50, step=10)

    try:
        dados = api.listar_jobs(
            status=None if status == "todos" else status,
            plataforma=None if plataforma == "todas" else plataforma,
            limit=limite,
        )
    except APIError as exc:
        st.error(f"Nao consegui listar os jobs: {exc.detail}")
        return []

    jobs = dados["items"]
    if not jobs:
        st.info("Nenhum job com esses filtros.")
        return []

    tabela = pd.DataFrame(
        [
            {
                "": ICONE_STATUS.get(j["status"], "•"),
                "id": j["id"][:8],
                "plataforma": j["plataforma"],
                "status": j["status"],
                "etapa": j["etapa"],
                "tentativas": j["attempts"],
                "carrossel": j["carousel_url"] or "",
                "criado em": pd.to_datetime(j["created_at"]).strftime("%d/%m %H:%M"),
                "url": j["url"],
            }
            for j in jobs
        ]
    )
    st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        column_config={
            "carrossel": st.column_config.LinkColumn("carrossel", display_text="abrir"),
            "url": st.column_config.LinkColumn("url", display_text="video"),
        },
    )
    return jobs


# --------------------------------------------------------------------------- #
# Detalhe
# --------------------------------------------------------------------------- #
def bloco_detalhe(api: PainelAPI, jobs: list[dict]) -> None:
    st.subheader("Detalhe")
    rotulos = {
        f"{ICONE_STATUS.get(j['status'], '•')} {j['id'][:8]} — {j['plataforma']} — {j['status']}": j["id"]
        for j in jobs
    }
    escolhido = st.selectbox("Job", list(rotulos), index=0)
    job_id = rotulos[escolhido]

    try:
        job = api.detalhar_job(job_id)
    except APIError as exc:
        st.error(f"Nao consegui abrir o job: {exc.detail}")
        return

    esquerda, direita = st.columns([2, 1])

    with esquerda:
        st.markdown(f"**URL:** {job['url']}")
        st.markdown(
            f"**Status:** {ICONE_STATUS.get(job['status'], '')} `{job['status']}` "
            f"· **etapa:** `{job['etapa']}` · **tentativas:** {job['attempts']}"
        )
        if job.get("error"):
            st.error(f"Etapa `{job['etapa']}` falhou: {job['error']}")
        if job.get("carousel_url"):
            st.link_button("Abrir carrossel", job["carousel_url"], type="primary")

        if job.get("transcript"):
            with st.expander("Transcricao", expanded=not job.get("slides_json")):
                st.write(job["transcript"])
        if job.get("slides_json"):
            with st.expander("Slides gerados", expanded=True):
                st.json(job["slides_json"])

    with direita:
        st.markdown("**Historico**")
        for evento in reversed(job.get("events", [])):
            carimbo = pd.to_datetime(evento["created_at"]).strftime("%d/%m %H:%M:%S")
            linha = f"`{carimbo}` {ICONE_STATUS.get(evento['status'], '•')} **{evento['etapa']}**"
            if evento.get("mensagem"):
                linha += f" — {evento['mensagem']}"
            st.markdown(linha)

        st.divider()
        pode_reprocessar = job["status"] in {"erro", "concluido"}
        if st.button(
            "Reprocessar", disabled=not pode_reprocessar, width="stretch"
        ):
            try:
                api.reprocessar(job_id)
                st.success("Job recolocado na fila.")
                st.rerun()
            except APIError as exc:
                st.error(f"Nao deu para reprocessar: {exc.detail}")


def main() -> None:
    st.title("🎠 Painel de Transcricao e Carrossel")
    api = sidebar()
    bloco_envio(api)
    st.divider()
    bloco_metricas(api)
    jobs = bloco_lista(api)
    if jobs:
        st.divider()
        bloco_detalhe(api, jobs)

    if st.session_state.get("auto_refresh"):
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
