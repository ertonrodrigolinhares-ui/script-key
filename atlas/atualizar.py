"""FASE 4 — Robô de atualização: baixa as páginas de ia/atualizar.txt para a base.

    python -m atlas.atualizar

Cada página vira um .md em ia/conhecimento/atualizacoes/, com a data da coleta.
Para rodar todo dia, agende o "Atualizar Base.bat /agendado" no Agendador de Tarefas do Windows
(veja o README).
"""

import re
import sys
import unicodedata
from datetime import datetime
from html.parser import HTMLParser

import httpx2

from .especialidade import _linhas, pasta_ia

LIMITE_POR_PAGINA = 100_000  # caracteres


class _Texto(HTMLParser):
    IGNORAR = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
    BLOCOS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}

    def __init__(self):
        super().__init__()
        self.partes, self._ignorando = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorando += 1
        elif tag in self.BLOCOS:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._ignorando:
            self._ignorando -= 1

    def handle_data(self, data):
        if not self._ignorando:
            self.partes.append(data)


def html_para_texto(html: str) -> str:
    leitor = _Texto()
    leitor.feed(html)
    texto = "".join(leitor.partes)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def paginas() -> list[tuple[str, str]]:
    lista = []
    for linha in _linhas("atualizar.txt"):
        if "|" not in linha:
            continue
        nome, url = (p.strip() for p in linha.split("|", 1))
        nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
        nome = re.sub(r"[^A-Za-z0-9-]+", "-", nome).strip("-").lower()
        if nome and url.startswith(("http://", "https://")):
            lista.append((nome, url))
    return lista


TIPOS_TEXTO = ("text/", "application/xhtml", "application/xml", "application/json")


def _e_texto(resposta: httpx2.Response) -> bool:
    """Só páginas de texto entram na base; PDF, Word, imagens etc. ficam de fora."""
    tipo = resposta.headers.get("content-type", "").split(";")[0].strip().lower()
    if tipo:
        return tipo.startswith(TIPOS_TEXTO)
    return b"\x00" not in resposta.content[:2048] and not resposta.content.startswith(b"%PDF")


def _texto_da_resposta(resposta: httpx2.Response) -> str:
    if resposta.charset_encoding:  # o servidor disse o charset no cabeçalho
        return resposta.text
    try:
        return resposta.content.decode("utf-8-sig")
    except UnicodeDecodeError:  # páginas antigas (ex.: leis geradas no Word) em windows-1252
        return resposta.content.decode("cp1252", errors="replace")


def atualizar(cliente: httpx2.Client | None = None) -> list[str]:
    """Baixa cada página e devolve um relatório (uma linha por página)."""
    destino = pasta_ia() / "conhecimento" / "atualizacoes"
    destino.mkdir(parents=True, exist_ok=True)
    cliente = cliente or httpx2.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Atlas/1.0"})
    relatorio = []
    for nome, url in paginas():
        try:
            resposta = cliente.get(url)
            resposta.raise_for_status()
        except httpx2.HTTPError as e:
            relatorio.append(f"FALHOU  {nome}: {e}")
            continue
        if not _e_texto(resposta):
            tipo = resposta.headers.get("content-type", "desconhecido")
            relatorio.append(
                f"IGNORADO {nome}: não é uma página de texto ({tipo}). Se for PDF, abra, copie o "
                "texto e salve como .txt em ia/conhecimento."
            )
            continue
        bruto = _texto_da_resposta(resposta)
        tipo = resposta.headers.get("content-type", "")
        texto = html_para_texto(bruto) if "html" in tipo or "<html" in bruto[:500].lower() else bruto
        aviso = ""
        if len(texto) > LIMITE_POR_PAGINA:
            texto = texto[:LIMITE_POR_PAGINA] + "\n\n[... página cortada: o resto não foi guardado ...]"
            aviso = " (página grande: guardei só o começo)"
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        try:
            (destino / f"{nome}.md").write_text(
                f"# {nome}\nFonte: {url}\nColetado em: {agora}\n\n{texto}\n", encoding="utf-8"
            )
        except OSError as e:
            relatorio.append(f"FALHOU  {nome}: não consegui gravar o arquivo ({e})")
            continue
        relatorio.append(f"OK      {nome}: {len(texto):,} caracteres{aviso}".replace(",", "."))
    if not relatorio:
        relatorio.append("Nenhuma página em ia/atualizar.txt. Nada a fazer.")
    return relatorio


if __name__ == "__main__":
    for linha in atualizar():
        print(linha)
    sys.exit(0)
