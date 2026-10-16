"""FASE 4 — Robô de atualização: baixa as páginas de ia/atualizar.txt para a base.

    python -m atlas.atualizar

Cada página vira um .md em ia/conhecimento/atualizacoes/, com a data da coleta.
Para rodar toda madrugada, agende o "Atualizar Base.bat" no Agendador de Tarefas do Windows.
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
        tipo = resposta.headers.get("content-type", "")
        texto = html_para_texto(resposta.text) if "html" in tipo or "<html" in resposta.text[:500].lower() else resposta.text
        texto = texto[:LIMITE_POR_PAGINA]
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        (destino / f"{nome}.md").write_text(
            f"# {nome}\nFonte: {url}\nColetado em: {agora}\n\n{texto}\n", encoding="utf-8"
        )
        relatorio.append(f"OK      {nome}: {len(texto):,} caracteres".replace(",", "."))
    if not relatorio:
        relatorio.append("Nenhuma página em ia/atualizar.txt. Nada a fazer.")
    return relatorio


if __name__ == "__main__":
    for linha in atualizar():
        print(linha)
    sys.exit(0)
