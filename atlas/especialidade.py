"""Lê a definição da IA na pasta ia/: instruções, documentos e fontes.

A definição é lida no começo de cada conversa: editar os arquivos vale a partir da
próxima conversa (botão "Nova conversa"). Assim a conversa em andamento não muda
de regras no meio do caminho.
A pasta pode ser trocada com a variável de ambiente ATLAS_IA.
"""

import ipaddress
import os
import re
from pathlib import Path

from .persona import SISTEMA

LIMITE_DOCUMENTOS = 600_000  # caracteres (~150 mil tokens); o resto é ignorado e avisado
LIMITE_FONTES = 64
EXTENSOES = {".md", ".txt"}
PENDENTE = "[DEFINIR"
# Terminações que o Claude não aceita sozinhas como site (são "famílias" de sites).
SUFIXOS_PUBLICOS = {
    "br", "com.br", "gov.br", "jus.br", "leg.br", "org.br", "net.br", "edu.br", "mp.br",
    "def.br", "tc.br", "mil.br", "com", "org", "net", "gov", "edu", "co.uk", "com.pt", "pt",
}


def pasta_ia() -> Path:
    pasta = os.environ.get("ATLAS_IA")
    return Path(pasta) if pasta else Path(__file__).resolve().parent.parent / "ia"


def ler(arquivo: Path) -> str:
    """Lê texto salvo por qualquer editor do Windows: UTF-8 (com ou sem BOM), UTF-16 ou ANSI."""
    dados = arquivo.read_bytes()
    if dados[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return dados.decode("utf-16", errors="replace")
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def _sem_anotacoes(texto: str) -> str:
    """Tira as anotações <!-- ... --> e as linhas [DEFINIR] ainda não preenchidas."""
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
    texto = "\n".join(l for l in texto.splitlines() if PENDENTE not in l)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _linhas(nome: str) -> list[str]:
    arquivo = pasta_ia() / nome
    if not arquivo.exists():
        return []
    return [l.strip() for l in ler(arquivo).splitlines() if l.strip() and not l.strip().startswith("#")]


def instrucoes() -> str:
    arquivo = pasta_ia() / "instrucoes.md"
    if arquivo.exists():
        texto = _sem_anotacoes(ler(arquivo))
        if texto:
            return texto
    return SISTEMA


def pendentes() -> int:
    """Quantos itens [DEFINIR] ainda faltam preencher em instrucoes.md."""
    arquivo = pasta_ia() / "instrucoes.md"
    if not arquivo.exists():
        return 0
    sem_comentarios = re.sub(r"<!--.*?-->", "", ler(arquivo), flags=re.DOTALL)
    return sum(1 for l in sem_comentarios.splitlines() if PENDENTE in l)


def documentos() -> tuple[str, list[str]]:
    """Junta os documentos de ia/conhecimento. Devolve (texto, arquivos deixados de fora)."""
    pasta = pasta_ia() / "conhecimento"
    if not pasta.exists():
        return "", []
    partes, total, fora = [], 0, []
    for arquivo in sorted(pasta.rglob("*")):
        if arquivo.suffix.lower() not in EXTENSOES or arquivo.name.upper().startswith("LEIA-ME"):
            continue
        conteudo = ler(arquivo).strip()
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


def _host(linha: str) -> str:
    """Extrai o site de uma linha: aceita endereço completo e ignora notas depois de # ou espaço."""
    partes = linha.split("#")[0].split()
    if not partes:
        return ""
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", partes[0].lower())
    host = re.split(r"[/?#]", host)[0]
    host = host.rsplit("@", 1)[-1].split(":")[0].removeprefix("*.").strip(".")
    return host


def _valido(host: str) -> bool:
    if "." not in host or host in SUFIXOS_PUBLICOS or host.startswith("localhost"):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return bool(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host))


def fontes() -> tuple[list[str], list[str]]:
    """Sites de ia/fontes.txt: (aceitos, linhas recusadas)."""
    aceitos, recusados = [], []
    for linha in _linhas("fontes.txt"):
        host = _host(linha)
        if not host:
            continue
        if not _valido(host):
            recusados.append(linha)
        elif host not in aceitos and len(aceitos) < LIMITE_FONTES:
            aceitos.append(host)
    return aceitos, recusados


def dominios() -> list[str]:
    return fontes()[0]


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
    """O que está configurado, para mostrar em ⚙ Configurar. Nunca levanta erro."""
    try:
        texto_docs, fora = documentos()
        aceitos, recusados = fontes()
        return {
            "pasta": str(pasta_ia()),
            "documentos": texto_docs.count("<documento "),
            "documentos_fora": fora,
            "fontes": aceitos,
            "fontes_recusadas": recusados,
            "pendentes": pendentes(),
            "erro": "",
        }
    except Exception as e:  # noqa: BLE001 - a tela de configuração precisa abrir sempre
        return {
            "pasta": str(pasta_ia()), "documentos": 0, "documentos_fora": [], "fontes": [],
            "fontes_recusadas": [], "pendentes": 0, "erro": f"Não consegui ler a pasta ia/: {e}",
        }
