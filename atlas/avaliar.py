"""FASE 6 — Teste com perguntas reais: mede se a IA acerta.

    python -m atlas.avaliar

Faz cada pergunta de ia/perguntas_teste.json para a IA, e um avaliador (o Claude)
compara a resposta com a resposta esperada. O relatório sai em ia/resultado_teste.md
e é gravado a cada pergunta, então nada se perde se o teste parar no meio.
Cada pergunta roda numa conversa nova, com memória vazia e descartável:
o teste não lê nem altera a memória real.
Atenção: gasta créditos da Anthropic (2 chamadas por pergunta).
"""

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime

import anthropic

from .cerebro import Conversa
from .config import MODELO, ler_chave
from .especialidade import ler, pasta_ia

AVALIADOR = (
    "Você avalia respostas de um assistente de IA. Compare a RESPOSTA com a RESPOSTA ESPERADA. "
    "A resposta está CERTA se contém o essencial da esperada (números, prazos, conclusão, ou a "
    "recusa quando a esperada pede recusa) e não afirma nada que a contradiga. Detalhes extras "
    "corretos não tiram ponto. Responda na primeira linha só CERTO ou ERRADO; na segunda, o motivo "
    "em uma frase."
)


class PerguntasInvalidas(Exception):
    """Problema no arquivo ia/perguntas_teste.json, explicado em português."""


def carregar_perguntas() -> tuple[list[dict], int]:
    """Devolve (perguntas válidas, quantas foram ignoradas por faltar campo)."""
    arquivo = pasta_ia() / "perguntas_teste.json"
    if not arquivo.exists():
        raise PerguntasInvalidas(f"Não encontrei {arquivo}.")
    try:
        dados = json.loads(ler(arquivo))
    except json.JSONDecodeError as e:
        raise PerguntasInvalidas(
            f"Erro de digitação em perguntas_teste.json, linha {e.lineno}, coluna {e.colno}: {e.msg}. "
            "Confira aspas, vírgulas e colchetes perto desse ponto."
        ) from None
    if not isinstance(dados, list):
        raise PerguntasInvalidas("perguntas_teste.json precisa ser uma lista: [ {...}, {...} ].")
    validas = [
        p for p in dados
        if isinstance(p, dict) and str(p.get("pergunta", "")).strip() and str(p.get("resposta_esperada", "")).strip()
    ]
    return validas, len(dados) - len(validas)


@contextmanager
def _memoria_descartavel():
    """Troca a pasta de dados por uma temporária enquanto o teste roda."""
    anterior = os.environ.get("ATLAS_PASTA")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ATLAS_PASTA"] = tmp
        try:
            yield
        finally:
            if anterior is None:
                os.environ.pop("ATLAS_PASTA", None)
            else:
                os.environ["ATLAS_PASTA"] = anterior


def responder(pergunta: str, cliente: anthropic.Anthropic | None) -> str:
    """Resposta da IA numa conversa nova, com memória vazia e descartável."""
    texto = ""
    with _memoria_descartavel():
        for evento in Conversa(cliente).responder(pergunta):
            if evento["tipo"] == "texto":
                texto += evento["texto"]
            elif evento["tipo"] == "descartar":
                texto = texto[: len(texto) - len(evento["texto"])]
            elif evento["tipo"] == "erro":
                return f"[ERRO] {evento['texto']}"
    return texto.strip()


def julgar(cliente: anthropic.Anthropic, pergunta: str, esperada: str, resposta: str) -> tuple[bool | None, str]:
    """(True=certo, False=errado, None=não deu para avaliar, motivo)."""
    msg = cliente.messages.create(
        model=MODELO,
        max_tokens=8000,
        output_config={"effort": "low"},
        system=AVALIADOR,
        messages=[{"role": "user", "content": (
            f"PERGUNTA:\n{pergunta}\n\nRESPOSTA ESPERADA:\n{esperada}\n\nRESPOSTA:\n{resposta}"
        )}],
    )
    if getattr(msg, "stop_reason", "end_turn") == "refusal":
        return None, "o avaliador recusou analisar esta pergunta"
    texto = "".join(b.text for b in msg.content if b.type == "text").strip()
    primeira, _, motivo = texto.partition("\n")
    veredito = primeira.strip().upper()
    if veredito.startswith("CERTO"):
        return True, motivo.strip()
    if veredito.startswith("ERRADO"):
        return False, motivo.strip()
    return None, f"o avaliador não respondeu no formato esperado: {texto[:200]}"


def _gravar(cabecalho: str, linhas: list[str]) -> None:
    (pasta_ia() / "resultado_teste.md").write_text(cabecalho + "\n".join(linhas), encoding="utf-8")


def avaliar(cliente: anthropic.Anthropic | None = None) -> str:
    if cliente is None:
        chave = ler_chave()
        if not chave:
            return "Falta a chave da Anthropic. Configure no Atlas (⚙ Configurar)."
        cliente = anthropic.Anthropic(api_key=chave)
    try:
        perguntas, ignoradas = carregar_perguntas()
    except PerguntasInvalidas as e:
        return str(e)
    if not perguntas:
        return "Nenhuma pergunta válida em ia/perguntas_teste.json (cada uma precisa de \"pergunta\" e \"resposta_esperada\")."

    inicio = datetime.now().strftime("%d/%m/%Y %H:%M")
    linhas, certos, errados, sem_nota = [], 0, 0, 0
    for i, p in enumerate(perguntas, 1):
        print(f"[{i}/{len(perguntas)}] {p['pergunta'][:70]}")
        try:
            resposta = responder(p["pergunta"], cliente)
            if resposta.startswith("[ERRO]"):
                nota, motivo = False, "a IA não respondeu"
            else:
                nota, motivo = julgar(cliente, p["pergunta"], p["resposta_esperada"], resposta)
        except anthropic.APIError as e:
            resposta, nota, motivo = "", None, f"falha ao falar com o Claude: {e}"
        if nota is True:
            certos += 1
            selo = "✅ CERTO"
        elif nota is False:
            errados += 1
            selo = "❌ ERRADO"
        else:
            sem_nota += 1
            selo = "⚠️ NÃO AVALIADO"
        linhas.append(
            f"## {i}. {selo}\n\n**Pergunta:** {p['pergunta']}\n\n"
            f"**Esperado:** {p['resposta_esperada']}\n\n**Resposta da IA:**\n\n{resposta}\n\n"
            f"**Avaliação:** {motivo}\n"
        )
        avaliadas = certos + errados
        cabecalho = (
            f"# Resultado do teste — {inicio}\n\n"
            f"**Acertos: {certos} de {avaliadas}** ({(100 * certos // avaliadas) if avaliadas else 0}%)"
            + (f" · {sem_nota} não avaliada(s)" if sem_nota else "")
            + (f" · {ignoradas} pergunta(s) ignorada(s) por faltar campo" if ignoradas else "")
            + (f" · teste em andamento ({i} de {len(perguntas)})" if i < len(perguntas) else "")
            + "\n\nOnde errou: ajuste ia/instrucoes.md ou acrescente um documento em ia/conhecimento/, "
            "clique em Nova conversa e rode o teste de novo.\n\n"
        )
        _gravar(cabecalho, linhas)

    extra = f", {sem_nota} não avaliada(s)" if sem_nota else ""
    extra += f", {ignoradas} ignorada(s) por faltar campo" if ignoradas else ""
    return f"Acertos: {certos} de {certos + errados}{extra}. Relatório completo em {pasta_ia() / 'resultado_teste.md'}"


if __name__ == "__main__":
    print(avaliar())
    sys.exit(0)
