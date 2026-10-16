"""Cérebro do Atlas: conversa com o Claude, com pesquisa na web e memória.

`responder()` é um gerador de eventos para a tela:
    {"tipo": "texto", "texto": "..."}      pedaço da resposta
    {"tipo": "descartar", "texto": "..."}  apagar da tela um pedaço que não vale mais
    {"tipo": "status", "texto": "..."}     ex.: "Pesquisando na web..."
    {"tipo": "memoria", "texto": "..."}    confirmação de algo guardado ou esquecido
    {"tipo": "erro", "texto": "..."}       algo deu errado

Regra de ouro: o histórico enviado ao Claude precisa estar sempre válido. Se uma
pergunta falhar por qualquer motivo, ela sai do histórico inteira (e da tela).
"""

import json
from collections.abc import Iterator

import anthropic
import httpx2

from . import especialidade, memoria
from .config import ESFORCO, MODELO, ler_chave

BETAS = ["server-side-fallback-2026-07-01"]
MAX_VOLTAS = 8  # idas e vindas com ferramentas numa mesma resposta
MAX_JSON_INVALIDO = 2  # novas tentativas seguidas quando a entrada de uma ferramenta vem quebrada

FERRAMENTAS_MEMORIA = [
    {
        "name": "guardar_memoria",
        "description": (
            "Guarda um fato duradouro sobre o usuário ou as preferências dele, "
            "para lembrar em conversas futuras. Uma frase curta e "
            "autoexplicativa por fato. Nunca use para senhas, chaves ou dados de clientes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"fato": {"type": "string", "description": "O fato a guardar."}},
            "required": ["fato"],
        },
    },
    {
        "name": "esquecer_memoria",
        "description": "Apaga da memória os fatos que contêm o trecho informado.",
        "input_schema": {
            "type": "object",
            "properties": {"trecho": {"type": "string", "description": "Trecho do fato a apagar."}},
            "required": ["trecho"],
        },
    },
]


class _Desfazer(Exception):
    """A pergunta falhou: desfaz o histórico e mostra a mensagem."""


def _executar_ferramenta(nome: str, entrada: object) -> tuple[str, bool]:
    """Roda uma ferramenta local. Devolve (resultado, é_erro). Nunca levanta exceção."""
    try:
        if not isinstance(entrada, dict):
            return "Entrada inválida.", True
        if nome == "guardar_memoria":
            fato = entrada.get("fato")
            if not isinstance(fato, str) or not fato.strip():
                return "Campo 'fato' ausente ou vazio.", True
            resultado = memoria.guardar(fato)
            return resultado, resultado in memoria.ERROS
        if nome == "esquecer_memoria":
            trecho = entrada.get("trecho")
            if not isinstance(trecho, str) or not trecho.strip():
                return "Campo 'trecho' ausente ou vazio.", True
            resultado = memoria.esquecer(trecho)
            return resultado, resultado in memoria.ERROS
        return f"Ferramenta desconhecida: {nome}", True
    except Exception as e:  # noqa: BLE001 - a resposta ao Claude precisa existir sempre
        return f"Falha ao executar a ferramenta: {e}", True


def _blocos_validos(conteudo: list, pausado: bool) -> list:
    """Limpa a resposta antes de guardá-la no histórico.

    - Depois de um fallback, descarta pensamentos e chamadas de ferramenta que o
      modelo que recusou deixou pela metade (tudo antes do último bloco "fallback").
    - Descarta pesquisas na web (server_tool_use) sem resultado, exceto quando a
      resposta foi pausada (pause_turn), porque aí o Claude continua de onde parou.
    """
    blocos = list(conteudo)
    corte = max((i for i, b in enumerate(blocos) if b.type == "fallback"), default=-1)
    pareados = {getattr(b, "tool_use_id", None) for b in blocos}
    limpos = []
    for i, b in enumerate(blocos):
        if i < corte and b.type in ("thinking", "redacted_thinking", "tool_use"):
            continue
        sem_resultado = b.type == "server_tool_use" and b.id not in pareados
        if sem_resultado and (i < corte or not pausado):
            continue
        limpos.append(b)
    return limpos


CONVERSA_LONGA = "A conversa ficou longa demais. Clique em Nova conversa para continuar."


def _mensagem_erro_api(e: anthropic.APIStatusError) -> str:
    erro = (e.body.get("error") or {}) if isinstance(e.body, dict) else {}
    tipo, detalhe = erro.get("type", ""), erro.get("message", "")
    if tipo in ("overloaded_error", "api_error") or e.status_code in (200, 500, 529):
        return "O Claude está sobrecarregado agora. Tente de novo em instantes."
    if e.status_code == 413 or "prompt is too long" in detalhe:
        return CONVERSA_LONGA
    if "allowed_domains" in detalhe:
        return f"Um site de ia/fontes.txt não foi aceito pelo Claude: {detalhe}. Corrija essa linha e clique em Nova conversa."
    if "bound to a different conversation" in detalhe:
        return "A definição da IA mudou durante esta conversa. Clique em Nova conversa."
    if detalhe:  # ex.: créditos acabaram; tentar de novo não resolveria
        return f"O Claude recusou o pedido (erro {e.status_code}): {detalhe}"
    return f"O Claude respondeu com erro {e.status_code}. Tente de novo."


def mensagem_de_abertura() -> str:
    """Primeira mensagem de cada conversa: o que o Atlas lembra."""
    return (
        "<memoria>\nFatos que você guardou em conversas anteriores:\n"
        f"{memoria.como_texto()}\n</memoria>"
    )


class Conversa:
    """Uma conversa com histórico completo (o Claude não guarda estado)."""

    def __init__(self, cliente: anthropic.Anthropic | None = None):
        self._cliente = cliente
        self.mensagens: list[dict] = []
        self._definicao: tuple[list[dict], list[dict]] | None = None  # (system, ferramentas)

    def trocar_chave(self) -> None:
        """A próxima pergunta cria o cliente de novo, com a chave atual."""
        self._cliente = None

    def _obter_cliente(self) -> anthropic.Anthropic:
        if self._cliente is None:
            chave = ler_chave()
            if not chave:
                raise RuntimeError("SEM_CHAVE")
            self._cliente = anthropic.Anthropic(api_key=chave)
        return self._cliente

    def responder(self, texto: str) -> Iterator[dict]:
        try:
            cliente = self._obter_cliente()
        except RuntimeError:
            yield {"tipo": "erro", "texto": "Falta a chave da Anthropic. Clique em ⚙ Configurar."}
            return

        if not self.mensagens or self._definicao is None:
            # A definição da IA (pasta ia/) vale para a conversa inteira: mudar o system
            # ou as ferramentas no meio invalidaria o raciocínio já guardado no histórico.
            try:
                self._definicao = (
                    especialidade.sistema(),
                    [especialidade.pesquisa_web(), *FERRAMENTAS_MEMORIA],
                )
            except (OSError, ValueError) as e:
                yield {"tipo": "erro", "texto": f"Não consegui ler a pasta ia/ (definição da IA): {e}"}
                return

        inicio = len(self.mensagens)
        mostrado = ""  # tudo o que esta pergunta já pôs na tela
        try:
            if not self.mensagens:
                texto = f"{mensagem_de_abertura()}\n\n{texto}"
            self.mensagens.append({"role": "user", "content": texto})
            for evento in self._voltas(cliente):
                if evento["tipo"] == "texto":
                    mostrado += evento["texto"]
                elif evento["tipo"] == "descartar":
                    mostrado = mostrado[: len(mostrado) - len(evento["texto"])]
                yield evento
        except _Desfazer as e:
            del self.mensagens[inicio:]
            if mostrado:
                yield {"tipo": "descartar", "texto": mostrado}
            yield {"tipo": "erro", "texto": str(e)}
        except BaseException:
            # Erro inesperado ou tela fechada no meio: o histórico volta ao ponto de partida.
            del self.mensagens[inicio:]
            raise

    def _voltas(self, cliente: anthropic.Anthropic) -> Iterator[dict]:
        sistema, ferramentas = self._definicao
        voltas = 0
        json_invalido = 0
        texto_anterior = ""
        while voltas < MAX_VOLTAS:
            texto_volta = ""
            try:
                with cliente.beta.messages.stream(
                    model=MODELO,
                    max_tokens=64000,
                    betas=BETAS,
                    fallbacks="default",
                    system=sistema,
                    output_config={"effort": ESFORCO},
                    tools=ferramentas,
                    messages=self.mensagens,
                ) as fluxo:
                    for evento in fluxo:
                        if evento.type == "text":
                            pedaco = evento.text
                            if not texto_volta and texto_anterior and not texto_anterior[-1].isspace():
                                pedaco = "\n\n" + pedaco  # separa o texto de voltas diferentes
                            texto_volta += pedaco
                            yield {"tipo": "texto", "texto": pedaco}
                        elif (
                            evento.type == "content_block_start"
                            and evento.content_block.type == "server_tool_use"
                        ):
                            yield {"tipo": "status", "texto": "Pesquisando na web..."}
                    final = fluxo.get_final_message()
            except ValueError:
                # Entrada de ferramenta em JSON inválido: descarta esta volta e tenta de novo.
                if texto_volta:
                    yield {"tipo": "descartar", "texto": texto_volta}
                json_invalido += 1
                if json_invalido > MAX_JSON_INVALIDO:
                    raise _Desfazer("O Claude gerou uma resposta inválida. Tente de novo.") from None
                continue
            except anthropic.AuthenticationError:
                raise _Desfazer("A chave da Anthropic foi recusada. Confira em ⚙ Configurar.") from None
            except anthropic.RateLimitError:
                raise _Desfazer("Muitos pedidos ao mesmo tempo. Espere um minuto e tente de novo.") from None
            except anthropic.APIStatusError as e:
                raise _Desfazer(_mensagem_erro_api(e)) from None
            except (anthropic.APIConnectionError, httpx2.TransportError):
                raise _Desfazer("A conexão com o Claude caiu. Confira a internet e tente de novo.") from None

            json_invalido = 0
            voltas += 1
            motivo = final.stop_reason
            if motivo is None:  # a transmissão terminou sem o fim da mensagem
                raise _Desfazer("A conexão com o Claude caiu. Confira a internet e tente de novo.")
            if motivo == "refusal":
                raise _Desfazer("O Claude não pôde responder a esse pedido.")

            blocos = _blocos_validos(final.content, pausado=motivo == "pause_turn")
            if not any(b.type != "fallback" for b in blocos):
                if motivo == "pause_turn":
                    continue
                if motivo == "model_context_window_exceeded":
                    raise _Desfazer(CONVERSA_LONGA)
                raise _Desfazer("O Claude não respondeu nada. Tente de novo.")
            self.mensagens.append({"role": "assistant", "content": [b.to_dict() for b in blocos]})
            texto_anterior += texto_volta
            pendentes = [b for b in blocos if b.type == "tool_use"]

            if motivo == "pause_turn":
                continue

            if motivo == "tool_use":
                resultados = []
                for bloco in pendentes:
                    resultado, falhou = _executar_ferramenta(bloco.name, bloco.input)
                    if not falhou:
                        yield {"tipo": "memoria", "texto": resultado}
                    resultados.append(
                        {"type": "tool_result", "tool_use_id": bloco.id, "content": resultado, "is_error": falhou}
                    )
                if resultados:
                    self.mensagens.append({"role": "user", "content": resultados})
                    continue
                return

            # Qualquer outro fim (end_turn, max_tokens, contexto cheio...): fecha
            # ferramentas pendentes para o histórico continuar válido.
            if pendentes:
                self.mensagens.append({"role": "user", "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": "A resposta foi interrompida; nada foi executado.",
                        "is_error": True,
                    }
                    for b in pendentes
                ]})
            if motivo == "max_tokens":
                yield {"tipo": "status", "texto": "Resposta cortada por ser longa demais."}
            elif motivo == "model_context_window_exceeded":
                yield {"tipo": "erro", "texto": CONVERSA_LONGA}
            return

        raise _Desfazer("A resposta precisou de passos demais. Tente reformular.")

    def exportar(self) -> str:
        return json.dumps(self.mensagens, ensure_ascii=False)
