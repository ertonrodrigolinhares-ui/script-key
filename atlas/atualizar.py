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

from .especialidade import RELATORIO_ROBO, _linhas, decodificar, pasta_ia

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
        return tipo.startswith(TIPOS_TEXTO) or tipo.endswith(("+xml", "+json"))  # inclui RSS/Atom
    return b"\x00" not in resposta.content[:2048] and not resposta.content.startswith(b"%PDF")


def _charset_declarado(dados: bytes) -> str:
    """Charset declarado dentro da página (<meta charset> ou <?xml encoding>)."""
    inicio = dados[:4096].decode("ascii", errors="ignore")
    achado = re.search(r"""<meta[^>]+charset=["']?\s*([\w-]+)""", inicio, re.I) or re.search(
        r"""<\?xml[^>]+encoding=["']([\w-]+)""", inicio, re.I
    )
    return achado.group(1).lower() if achado else ""


def _texto_da_resposta(resposta: httpx2.Response) -> str:
    """Decodifica como o navegador: cabeçalho, depois o que a página declara, depois detecção."""
    dados = resposta.content
    for charset in (resposta.charset_encoding, _charset_declarado(dados)):
        if not charset:
            continue
        charset = charset.lower()
        if charset in ("iso-8859-1", "latin-1", "latin1", "us-ascii", "ascii", "x-cp1252"):
            charset = "cp1252"  # o que os navegadores fazem com esses rótulos
        try:
            return dados.decode(charset, errors="replace")
        except LookupError:
            continue
    return decodificar(dados)


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
            dica = ""
            if "pdf" in tipo or "word" in tipo or resposta.content.startswith(b"%PDF"):
                dica = " Se for PDF ou Word, abra, copie o texto e salve como .txt em ia/conhecimento."
            relatorio.append(f"IGNORADO {nome}: não é uma página de texto ({tipo}).{dica}")
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


def gravar_relatorio(relatorio: list[str]) -> None:
    """Guarda o resultado da última execução (aparece em ⚙ Configurar)."""
    ok = sum(1 for l in relatorio if l.startswith("OK"))
    falhas = sum(1 for l in relatorio if l.startswith("FALHOU"))
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    resumo = f"{agora}: {ok} página(s) atualizada(s)" + (f", {falhas} com falha" if falhas else "")
    destino = pasta_ia() / "conhecimento" / "atualizacoes" / RELATORIO_ROBO
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(resumo + "\n\n" + "\n".join(relatorio) + "\n", encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    linhas = atualizar()
    for linha in linhas:
        print(linha)
    gravar_relatorio(linhas)
    sys.exit(1 if any(l.startswith("FALHOU") for l in linhas) else 0)
