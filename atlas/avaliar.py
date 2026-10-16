"""FASE 6 — Teste com perguntas reais: mede se a IA acerta.

    python -m atlas.avaliar

Faz cada pergunta de ia/perguntas_teste.json para a IA, e um avaliador (o Claude)
compara a resposta com a resposta esperada. O relatório sai em ia/resultado_teste.md.
Atenção: gasta créditos da Anthropic (2 chamadas por pergunta).
"""

import json
import sys
from datetime import datetime

import anthropic

from .cerebro import Conversa
from .config import MODELO, ler_chave
from .especialidade import pasta_ia

AVALIADOR = (
    "Você avalia respostas de um assistente de IA. Compare a RESPOSTA com a RESPOSTA ESPERADA. "
    "A resposta está CERTA se contém o essencial da esperada (números, prazos, conclusão, ou a "
    "recusa quando a esperada pede recusa) e não afirma nada que a contradiga. Detalhes extras "
    "corretos não tiram ponto. Responda na primeira linha só CERTO ou ERRADO; na segunda, o motivo "
    "em uma frase."
)


def carregar_perguntas() -> list[dict]:
    dados = json.loads((pasta_ia() / "perguntas_teste.json").read_text(encoding="utf-8-sig"))
    return [p for p in dados if isinstance(p, dict) and p.get("pergunta") and p.get("resposta_esperada")]


def responder(pergunta: str, cliente: anthropic.Anthropic | None) -> str:
    """Resposta da IA numa conversa nova, sem memória de testes anteriores."""
    texto = ""
    for evento in Conversa(cliente).responder(pergunta):
        if evento["tipo"] == "texto":
            texto += evento["texto"]
        elif evento["tipo"] == "descartar":
            texto = texto[: len(texto) - len(evento["texto"])]
        elif evento["tipo"] == "erro":
            return f"[ERRO] {evento['texto']}"
    return texto.strip()


def julgar(cliente: anthropic.Anthropic, pergunta: str, esperada: str, resposta: str) -> tuple[bool, str]:
    msg = cliente.messages.create(
        model=MODELO,
        max_tokens=2000,
        output_config={"effort": "low"},
        system=AVALIADOR,
        messages=[{"role": "user", "content": (
            f"PERGUNTA:\n{pergunta}\n\nRESPOSTA ESPERADA:\n{esperada}\n\nRESPOSTA:\n{resposta}"
        )}],
    )
    texto = "".join(b.text for b in msg.content if b.type == "text").strip()
    primeira, _, motivo = texto.partition("\n")
    return primeira.strip().upper().startswith("CERTO"), motivo.strip()


def avaliar(cliente: anthropic.Anthropic | None = None) -> str:
    if cliente is None:
        chave = ler_chave()
        if not chave:
            raise SystemExit("Falta a chave da Anthropic. Configure no Atlas (⚙ Configurar).")
        cliente = anthropic.Anthropic(api_key=chave)
    perguntas = carregar_perguntas()
    linhas, acertos = [], 0
    for i, p in enumerate(perguntas, 1):
        print(f"[{i}/{len(perguntas)}] {p['pergunta'][:70]}")
        resposta = responder(p["pergunta"], cliente)
        certo, motivo = (False, "a IA não respondeu") if resposta.startswith("[ERRO]") else julgar(
            cliente, p["pergunta"], p["resposta_esperada"], resposta
        )
        acertos += certo
        linhas.append(
            f"## {i}. {'✅ CERTO' if certo else '❌ ERRADO'}\n\n**Pergunta:** {p['pergunta']}\n\n"
            f"**Esperado:** {p['resposta_esperada']}\n\n**Resposta da IA:**\n\n{resposta}\n\n"
            f"**Avaliação:** {motivo}\n"
        )
    total = len(perguntas)
    cabecalho = (
        f"# Resultado do teste — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"**Acertos: {acertos} de {total}** ({(100 * acertos // total) if total else 0}%)\n\n"
        "Onde errou: ajuste ia/instrucoes.md ou acrescente um documento em ia/conhecimento/, "
        "e rode o teste de novo.\n\n"
    )
    relatorio = cabecalho + "\n".join(linhas)
    (pasta_ia() / "resultado_teste.md").write_text(relatorio, encoding="utf-8")
    return f"Acertos: {acertos} de {total}. Relatório completo em {pasta_ia() / 'resultado_teste.md'}"


if __name__ == "__main__":
    print(avaliar())
    sys.exit(0)
