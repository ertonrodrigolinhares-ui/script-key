"""Lê a definição da IA na pasta ia/: instruções, documentos e fontes.

Tudo é lido a cada pergunta, então editar os arquivos vale na hora, sem reiniciar.
A pasta pode ser trocada com a variável de ambiente ATLAS_IA.
"""

import os
import re
from pathlib import Path

from .persona import SISTEMA

LIMITE_DOCUMENTOS = 600_000  # caracteres (~150 mil tokens); o resto é ignorado e avisado
EXTENSOES = {".md", ".txt"}


def pasta_ia() -> Path:
    pasta = os.environ.get("ATLAS_IA")
    return Path(pasta) if pasta else Path(__file__).resolve().parent.parent / "ia"


def _sem_anotacoes(texto: str) -> str:
    """Tira os comentários <!-- ... --> (anotações para quem edita, não para a IA)."""
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _linhas(nome: str) -> list[str]:
    arquivo = pasta_ia() / nome
    if not arquivo.exists():
        return []
    linhas = arquivo.read_text(encoding="utf-8-sig").splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]


def instrucoes() -> str:
    arquivo = pasta_ia() / "instrucoes.md"
    if arquivo.exists():
        texto = _sem_anotacoes(arquivo.read_text(encoding="utf-8-sig"))
        if texto:
            return texto
    return SISTEMA


def documentos() -> tuple[str, list[str]]:
    """Junta os documentos de ia/conhecimento. Devolve (texto, arquivos deixados de fora)."""
    pasta = pasta_ia() / "conhecimento"
    if not pasta.exists():
        return "", []
    partes, total, fora = [], 0, []
    for arquivo in sorted(pasta.rglob("*")):
        if arquivo.suffix.lower() not in EXTENSOES or arquivo.name.upper().startswith("LEIA-ME"):
            continue
        conteudo = arquivo.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not conteudo:
            continue
        nome = arquivo.relative_to(pasta).as_posix()
        if total + len(conteudo) > LIMITE_DOCUMENTOS:
            fora.append(nome)
            continue
        total += len(conteudo)
        partes.append(f'<documento nome="{nome}">\n{conteudo}\n</documento>')
    if not partes:
        return "", fora
    texto = (
        "Documentos de referência. Consulte-os antes de responder e cite o nome do "
        "documento quando usar uma informação dele.\n<documentos>\n"
        + "\n".join(partes)
        + "\n</documentos>"
    )
    return texto, fora


def dominios() -> list[str]:
    limpos = []
    for linha in _linhas("fontes.txt"):
        dominio = re.sub(r"^https?://", "", linha).split("/")[0].strip()
        if dominio:
            limpos.append(dominio)
    return limpos


def sistema() -> list[dict]:
    """Blocos do system prompt: instruções + documentos, com cache no último bloco."""
    blocos = [{"type": "text", "text": instrucoes()}]
    texto_docs, _ = documentos()
    if texto_docs:
        blocos.append({"type": "text", "text": texto_docs})
    blocos[-1]["cache_control"] = {"type": "ephemeral"}
    return blocos


def pesquisa_web() -> dict:
    ferramenta = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
    lista = dominios()
    if lista:
        ferramenta["allowed_domains"] = lista
    return ferramenta


def resumo() -> dict:
    """O que está configurado, para mostrar na tela."""
    texto_docs, fora = documentos()
    return {
        "pasta": str(pasta_ia()),
        "documentos": texto_docs.count("<documento "),
        "documentos_fora": fora,
        "fontes": dominios(),
    }
