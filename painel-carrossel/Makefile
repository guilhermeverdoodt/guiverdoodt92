.PHONY: help install dev api dashboard test fmt compose-up compose-down

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## cria o venv e instala as dependencias de dev
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -r requirements-dev.txt
	@test -f .env || cp .env.example .env

api:  ## sobe a API em http://localhost:8000
	.venv/bin/uvicorn app.main:app --reload --port 8000

dashboard:  ## sobe o painel em http://localhost:8501
	.venv/bin/streamlit run dashboard/streamlit_app.py

test:  ## roda os testes
	.venv/bin/pytest -q

compose-up:  ## sobe tudo (api + dashboard + postgres + n8n)
	docker compose up --build -d

compose-down:  ## derruba tudo
	docker compose down
