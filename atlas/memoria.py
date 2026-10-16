"""Memória de longo prazo do Atlas: fatos que o usuário pede para guardar."""

import json
import os
import tempfile
import threading
from datetime import date
from pathlib import Path

from .config import pasta_dados

ERRO_LEITURA = "Não consegui ler o memoria.json (arquivo corrompido?). Nada foi alterado."
ERRO_GRAVACAO = "Não consegui gravar o memoria.json agora (arquivo em uso?). Tente de novo."
ERROS = (ERRO_LEITURA, ERRO_GRAVACAO)

_trava = threading.Lock()  # a tela e o Claude podem mexer na memória ao mesmo tempo


def _arquivo() -> Path:
    return pasta_dados() / "memoria.json"


def _carregar() -> list[dict]:
    """Lê a memória; levanta erro se o arquivo existir mas estiver fora do formato."""
    arquivo = _arquivo()
    if not arquivo.exists():
        return []
    dados = json.loads(arquivo.read_text(encoding="utf-8-sig"))
    if not isinstance(dados, list) or not all(
        isinstance(f, dict) and isinstance(f.get("fato"), str) for f in dados
    ):
        raise ValueError("memoria.json fora do formato")
    return dados


def _gravar(fatos: list[dict]) -> None:
    """Grava num arquivo temporário e troca de uma vez, para nunca deixar o arquivo pela metade."""
    pasta = _arquivo().parent
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=pasta, prefix="memoria.", suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(json.dumps(fatos, ensure_ascii=False, indent=2))
    try:
        os.replace(tmp.name, _arquivo())
    except OSError:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def listar() -> list[dict]:
    """Para exibir: se o arquivo estiver ilegível, mostra a memória vazia sem alterar nada."""
    try:
        return _carregar()
    except (ValueError, OSError):
        return []


def guardar(fato: str) -> str:
    fato = fato.strip()
    if not fato:
        return "Nada para guardar."
    with _trava:
        try:
            fatos = _carregar()
        except (ValueError, OSError):
            return ERRO_LEITURA
        if any(f["fato"].lower() == fato.lower() for f in fatos):
            return "Isso já estava na memória."
        fatos.append({"fato": fato, "data": date.today().isoformat()})
        try:
            _gravar(fatos)
        except OSError:
            return ERRO_GRAVACAO
    return "Guardado na memória."


def esquecer(trecho: str, exato: bool = False) -> str:
    """Apaga os fatos que contêm o trecho (ou, com exato=True, só o fato idêntico)."""
    trecho = trecho.strip().lower()
    if not trecho:
        return "Nada para esquecer."
    with _trava:
        try:
            fatos = _carregar()
        except (ValueError, OSError):
            return ERRO_LEITURA
        if exato:
            restantes = [f for f in fatos if f["fato"].strip().lower() != trecho]
        else:
            restantes = [f for f in fatos if trecho not in f["fato"].lower()]
        if len(restantes) == len(fatos):
            return "Não encontrei nada parecido na memória."
        try:
            _gravar(restantes)
        except OSError:
            return ERRO_GRAVACAO
    return f"Esqueci {len(fatos) - len(restantes)} item(ns) da memória."


def como_texto() -> str:
    fatos = listar()
    if not fatos:
        return "(memória vazia)"
    return "\n".join(f"- {f['fato']} (guardado em {f.get('data', '?')})" for f in fatos)
