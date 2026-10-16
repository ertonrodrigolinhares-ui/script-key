"""Servidor local do Atlas: serve a tela de chat e conversa com o cérebro."""

import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import memoria
from .cerebro import Conversa
from .config import ler_chave, pasta_dados, salvar_chave

ESTATICOS = Path(__file__).parent / "static"

LOCAIS = ["127.0.0.1", "localhost"]

app = FastAPI(title="Atlas")


@app.middleware("http")
async def so_desta_pagina(request: Request, call_next):
    """Recusa pedidos que mudam algo vindos de outro site aberto no navegador (CSRF)."""
    origem = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origem is not None:
        if urlsplit(origem).hostname not in LOCAIS:
            return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
    return await call_next(request)


# Só aceita pedidos endereçados a este computador: impede que um site malicioso
# use o Atlas pelo navegador (DNS rebinding) para ler a memória ou trocar a chave.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAIS)

_conversas: dict[str, Conversa] = {}


class Pergunta(BaseModel):
    conversa: str | None = None
    texto: str


class Chave(BaseModel):
    chave: str


@app.get("/")
def pagina():
    return FileResponse(ESTATICOS / "index.html")


@app.get("/api/estado")
def estado():
    return {"tem_chave": bool(ler_chave()), "memoria": memoria.listar(), "pasta": str(pasta_dados())}


@app.post("/api/chave")
def gravar_chave(dados: Chave):
    try:
        salvar_chave(dados.chave)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    for conversa in _conversas.values():
        conversa.trocar_chave()  # mantém o histórico; a próxima pergunta já usa a chave nova
    return {"ok": True}


@app.delete("/api/memoria")
def apagar_memoria(trecho: str, exato: bool = False):
    if not trecho.strip():
        raise HTTPException(400, "Trecho vazio.")
    return {"mensagem": memoria.esquecer(trecho, exato=exato)}


@app.post("/api/chat")
def conversar(pergunta: Pergunta):
    texto = pergunta.texto.strip()
    if not texto:
        raise HTTPException(400, "Mensagem vazia.")
    conversa_id = pergunta.conversa if pergunta.conversa in _conversas else str(uuid.uuid4())
    nova = pergunta.conversa is not None and pergunta.conversa != conversa_id
    conversa = _conversas.setdefault(conversa_id, Conversa())

    def eventos():
        yield _sse({"tipo": "conversa", "id": conversa_id, "reiniciada": nova})
        try:
            for evento in conversa.responder(texto):
                yield _sse(evento)
        except Exception as e:  # a tela nunca fica sem resposta
            yield _sse({"tipo": "erro", "texto": f"Erro inesperado no Atlas: {e}"})
        yield _sse({"tipo": "fim"})

    return StreamingResponse(eventos(), media_type="text/event-stream")


def _sse(dados: dict) -> str:
    return f"data: {json.dumps(dados, ensure_ascii=False)}\n\n"
