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
# Textos de ajuda do modelo (ia/instrucoes.md). Linha [DEFINIR] ainda igual ao modelo = não preenchida.
AJUDAS = {
    "Especialidade: escreva aqui qual problema a IA resolve. Ex.: Você é especialista em ...",
    "Público: escreva para quem a IA responde e como tratar essa pessoa. Ex.: Você atende ...",
    'Assuntos: escreva um item por linha, começando com "- ".',
    "Outros limites: ex.: - Não responde sobre assuntos fora de ...",
    "Encaminhamento: quando passar o caso para um humano, e para quem.",
    "Formato: ex.: Responda sempre em: Resposta curta / Fundamento / Fonte.",
}
# Terminações que o Claude não aceita sozinhas como site (são "famílias" de sites).
SEGUNDO_NIVEL = {  # ex.: gov.br, com.au, co.uk, adv.br — são famílias, não sites
    "ac", "adm", "adv", "agr", "arq", "art", "blog", "bio", "cnt", "co", "com", "coop", "def",
    "ecn", "edu", "eng", "esp", "etc", "eti", "far", "fot", "g12", "ggf", "gov", "imb", "ind",
    "inf", "jor", "jus", "leg", "lel", "med", "mil", "mp", "mus", "ne", "net", "nom", "not",
    "ntr", "odo", "or", "org", "ppg", "pro", "psc", "psi", "qsl", "rec", "slg", "srv", "tc",
    "tmp", "trd", "tur", "tv", "vet", "zlg",
}
ESTADOS = {
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb",
    "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc", "sp", "se", "to",
}
REDES_INTERNAS = ("local", "internal", "localdomain", "localhost", "lan", "home", "corp", "intranet")


def pasta_ia() -> Path:
    pasta = os.environ.get("ATLAS_IA")
    return Path(pasta) if pasta else Path(__file__).resolve().parent.parent / "ia"


def decodificar(dados: bytes) -> str:
    """UTF-8 (com ou sem BOM), UTF-16 ou ANSI (Windows-1252), escolhendo pelo conteúdo."""
    if dados[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return dados.decode("utf-16", errors="replace")
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # Um ou outro byte estranho num texto UTF-8 não pode estragar todos os acentos:
    # só troca para ANSI se a maior parte do texto não for UTF-8.
    como_utf8 = dados.decode("utf-8-sig", errors="replace")
    estranhos = como_utf8.count("\ufffd")
    acentuados = sum(1 for c in como_utf8 if ord(c) > 127 and c != "\ufffd")
    if estranhos <= max(2, acentuados // 10):
        return como_utf8
    return dados.decode("cp1252", errors="replace")


def ler(arquivo: Path) -> str:
    """Lê texto salvo por qualquer editor do Windows."""
    return decodificar(arquivo.read_bytes())


def _linha_pendente(linha: str) -> bool:
    return PENDENTE in linha and re.sub(r"\[DEFINIR\]?:?\]?\s*", "", linha).strip() in AJUDAS


def _sem_anotacoes(texto: str) -> str:
    """Tira as anotações <!-- ... -->, as linhas [DEFINIR] ainda iguais ao modelo
    e a marca [DEFINIR] das linhas que o usuário já preencheu."""
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
    linhas = []
    for linha in texto.splitlines():
        if _linha_pendente(linha):
            continue
        linhas.append(re.sub(r"\[DEFINIR\]\s*", "", linha) if PENDENTE in linha else linha)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


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
    return sum(1 for l in sem_comentarios.splitlines() if _linha_pendente(l))


def documentos() -> tuple[str, list[str]]:
    """Junta os documentos de ia/conhecimento. Devolve (texto, arquivos deixados de fora)."""
    pasta = pasta_ia() / "conhecimento"
    if not pasta.exists():
        return "", []
    partes, total, fora = [], 0, []
    for arquivo in sorted(pasta.rglob("*")):
        if (
            arquivo.suffix.lower() not in EXTENSOES
            or arquivo.name.upper().startswith("LEIA-ME")
            or arquivo.name.startswith("_")
        ):
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
    """Extrai o site de uma linha. Aceita endereço completo, marcador de lista ("- ", "1.")
    e rótulo antes ("Planalto: ..."), e ignora notas depois de #."""
    partes = linha.split("#")[0].split()
    while partes and (re.fullmatch(r"[-*•·>]+|\d+[.)]", partes[0]) or partes[0].endswith(":")):
        partes.pop(0)
    if not partes:
        return ""
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", partes[0].lower())
    host = re.split(r"[/?#]", host)[0]
    host = host.rsplit("@", 1)[-1].split(":")[0].removeprefix("*.").strip(".")
    return host


def _valido(host: str) -> bool:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", host):
        return False
    rotulos = host.split(".")
    if all(r.isdigit() for r in rotulos) or rotulos[-1].isdigit():
        return False  # endereço IP
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    if rotulos[-1] in REDES_INTERNAS:
        return False
    if len(rotulos) == 2 and len(rotulos[-1]) == 2 and rotulos[0] in SEGUNDO_NIVEL:
        return False  # gov.br, com.au, co.uk...
    if len(rotulos) == 3 and rotulos[-1] == "br" and rotulos[1] in SEGUNDO_NIVEL and rotulos[0] in ESTADOS:
        return False  # sp.gov.br, pb.gov.br...
    return True


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


def pesquisa_web() -> dict | None:
    """Ferramenta de pesquisa na web. None = desligada (fontes.txt sem nenhum site válido)."""
    ferramenta = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
    aceitos, recusados = fontes()
    if aceitos:
        ferramenta["allowed_domains"] = aceitos
    elif recusados:
        return None  # o usuário quis restringir, mas nenhum site vale: melhor não pesquisar
    return ferramenta


def aviso_fontes() -> str:
    aceitos, recusados = fontes()
    if recusados and not aceitos:
        return "ia/fontes.txt não tem nenhum site válido, então a pesquisa na web está desligada. Veja ⚙ Configurar."
    if recusados:
        return f"Algumas linhas de ia/fontes.txt não são um site válido e foram ignoradas: {' | '.join(recusados)}"
    return ""


RELATORIO_ROBO = "_ultimo_relatorio.txt"


def _ultimo_relatorio() -> str:
    arquivo = pasta_ia() / "conhecimento" / "atualizacoes" / RELATORIO_ROBO
    return ler(arquivo).splitlines()[0] if arquivo.exists() else ""


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
            "pesquisa_desligada": bool(recusados and not aceitos),
            "robo": _ultimo_relatorio(),
            "erro": "",
        }
    except Exception as e:  # noqa: BLE001 - a tela de configuração precisa abrir sempre
        return {
            "pasta": str(pasta_ia()), "documentos": 0, "documentos_fora": [], "fontes": [],
            "fontes_recusadas": [], "pendentes": 0, "pesquisa_desligada": False, "robo": "",
            "erro": f"Não consegui ler a pasta ia/: {e}",
        }
