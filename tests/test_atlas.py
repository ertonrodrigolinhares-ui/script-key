"""Testes do Atlas sem gastar créditos: o Claude é substituído por um falso."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from atlas.cerebro import CONVERSA_LONGA


@pytest.fixture(autouse=True)
def pasta_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_PASTA", str(tmp_path))
    monkeypatch.setenv("ATLAS_IA", str(tmp_path / "ia"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from atlas import servidor

    servidor._conversas.clear()


class FluxoFalso:
    def __init__(self, textos, final):
        self._textos, self._final = textos, final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for t in self._textos:
            yield SimpleNamespace(type="text", text=t)

    def get_final_message(self):
        return self._final


class Bloco(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


class ClienteFalso:
    """Devolve as respostas da fila, uma por chamada. Uma exceção na fila é levantada."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.chamadas.append({**kwargs, "messages": list(kwargs["messages"])})
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        if isinstance(resposta, FluxoFalso):
            return resposta
        textos, final = resposta
        return FluxoFalso(textos, final)


def _texto(t):
    return ([t], SimpleNamespace(stop_reason="end_turn", content=[Bloco(type="text", text=t)]))


def _uso_memoria(fato="Prefere reuniões cedo", id_="t1"):
    uso = Bloco(type="tool_use", id=id_, name="guardar_memoria", input={"fato": fato})
    return ([], SimpleNamespace(stop_reason="tool_use", content=[uso]))


def _erro_conexao():
    return anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))


def _historico_valido(mensagens):
    """Todo tool_use do assistente tem tool_result logo em seguida, e nada fica vazio."""
    for i, m in enumerate(mensagens):
        assert m["content"], f"mensagem {i} vazia"
        if m["role"] == "assistant" and isinstance(m["content"], list):
            ids = {b["id"] for b in m["content"] if b["type"] == "tool_use"}
            if ids:
                seguinte = mensagens[i + 1]["content"]
                assert ids == {b["tool_use_id"] for b in seguinte if b.get("type") == "tool_result"}


# ---------- memória e configuração ----------

def test_memoria_guardar_e_esquecer():
    from atlas import memoria

    assert memoria.guardar("Reuniões sempre às 9h") == "Guardado na memória."
    assert memoria.guardar("reuniões sempre às 9h") == "Isso já estava na memória."
    assert "Reuniões" in memoria.como_texto()
    assert memoria.esquecer("reuniões") == "Esqueci 1 item(ns) da memória."
    assert memoria.como_texto() == "(memória vazia)"


def test_esquecer_exato_nao_apaga_parecidos():
    from atlas import memoria

    memoria.guardar("Prefere café")
    memoria.guardar("Prefere café sem açúcar")
    memoria.esquecer("Prefere café", exato=True)
    assert [f["fato"] for f in memoria.listar()] == ["Prefere café sem açúcar"]


def test_memoria_corrompida_nao_e_apagada():
    from atlas import memoria
    from atlas.config import pasta_dados

    arquivo = pasta_dados() / "memoria.json"
    arquivo.write_text("{isso não é json", encoding="utf-8")
    assert memoria.listar() == []
    assert memoria.guardar("Novo fato") == memoria.ERRO_LEITURA
    assert memoria.esquecer("x") == memoria.ERRO_LEITURA
    assert arquivo.read_text(encoding="utf-8") == "{isso não é json"


def test_chave_salva_e_validada():
    from atlas import config

    with pytest.raises(ValueError):
        config.salvar_chave("AIza-errada")
    config.salvar_chave("sk-ant-teste")
    assert config.ler_chave() == "sk-ant-teste"


def test_chave_salva_vale_mais_que_variavel_de_ambiente(monkeypatch):
    from atlas import config

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-antiga")
    assert config.ler_chave() == "sk-ant-antiga"
    config.salvar_chave("sk-ant-nova")
    assert config.ler_chave() == "sk-ant-nova"


# ---------- cérebro ----------

def test_resposta_simples_e_memoria_na_abertura():
    from atlas.cerebro import Conversa

    cliente = ClienteFalso([_texto("Olá!")])
    eventos = list(Conversa(cliente).responder("Oi"))
    assert eventos == [{"tipo": "texto", "texto": "Olá!"}]
    chamada = cliente.chamadas[0]
    assert chamada["model"] == "claude-opus-5-5"
    assert chamada["fallbacks"] == "default"
    assert "<memoria>" in chamada["messages"][0]["content"]


def test_ferramenta_guardar_memoria():
    from atlas import memoria
    from atlas.cerebro import Conversa

    cliente = ClienteFalso([_uso_memoria(), _texto("Anotado.")])
    conversa = Conversa(cliente)
    eventos = list(conversa.responder("Lembre que prefiro reuniões cedo"))
    assert {"tipo": "memoria", "texto": "Guardado na memória."} in eventos
    assert eventos[-1] == {"tipo": "texto", "texto": "Anotado."}
    assert memoria.listar()[0]["fato"] == "Prefere reuniões cedo"
    resultado = conversa.mensagens[2]["content"][0]
    assert resultado["type"] == "tool_result" and resultado["tool_use_id"] == "t1"
    _historico_valido(conversa.mensagens)


def test_recusa_nao_quebra_a_conversa():
    from atlas.cerebro import Conversa

    recusa = ([], SimpleNamespace(stop_reason="refusal", content=[]))
    cliente = ClienteFalso([_texto("Oi."), recusa, _texto("Claro.")])
    conversa = Conversa(cliente)
    list(conversa.responder("Oi"))
    eventos = list(conversa.responder("pergunta recusada"))
    assert eventos[-1]["tipo"] == "erro"
    assert len(conversa.mensagens) == 2  # a pergunta recusada saiu do histórico
    assert list(conversa.responder("outra pergunta"))[-1] == {"tipo": "texto", "texto": "Claro."}
    _historico_valido(conversa.mensagens)


def test_erro_depois_da_ferramenta_desfaz_a_pergunta_inteira():
    from atlas.cerebro import Conversa

    cliente = ClienteFalso([_uso_memoria(), _erro_conexao(), _texto("Agora foi.")])
    conversa = Conversa(cliente)
    eventos = list(conversa.responder("Lembre que prefiro reuniões cedo"))
    assert eventos[-1]["tipo"] == "erro"
    assert conversa.mensagens == []
    assert list(conversa.responder("de novo"))[-1] == {"tipo": "texto", "texto": "Agora foi."}
    assert "<memoria>" in cliente.chamadas[-1]["messages"][0]["content"]
    _historico_valido(conversa.mensagens)


def test_queda_de_conexao_no_meio_da_resposta():
    from atlas.cerebro import Conversa

    cliente = ClienteFalso([httpx2.RemoteProtocolError("caiu")])
    conversa = Conversa(cliente)
    eventos = list(conversa.responder("Oi"))
    assert eventos[-1]["tipo"] == "erro" and "conexão" in eventos[-1]["texto"]
    assert conversa.mensagens == []


def test_corte_por_tamanho_com_ferramenta_pendente():
    from atlas import memoria
    from atlas.cerebro import Conversa

    uso = Bloco(type="tool_use", id="t9", name="guardar_memoria", input={"fato": "Usuário tem"})
    cortada = ([], SimpleNamespace(stop_reason="max_tokens", content=[uso]))
    conversa = Conversa(ClienteFalso([cortada]))
    eventos = list(conversa.responder("Oi"))
    assert eventos[-1]["tipo"] == "status"
    assert memoria.listar() == []  # nada foi executado
    _historico_valido(conversa.mensagens)


def test_fallback_descarta_ferramenta_do_modelo_que_recusou():
    from atlas import memoria
    from atlas.cerebro import Conversa

    conteudo = [
        Bloco(type="tool_use", id="velho", name="guardar_memoria", input={"fato": "Usuário tem"}),
        Bloco(type="fallback"),
        Bloco(type="tool_use", id="novo", name="guardar_memoria", input={"fato": "Treina cedo"}),
    ]
    cliente = ClienteFalso([([], SimpleNamespace(stop_reason="tool_use", content=conteudo)), _texto("Ok.")])
    conversa = Conversa(cliente)
    list(conversa.responder("Lembre que treino cedo"))
    assert [f["fato"] for f in memoria.listar()] == ["Treina cedo"]
    assert [b["type"] for b in conversa.mensagens[1]["content"]] == ["fallback", "tool_use"]
    _historico_valido(conversa.mensagens)


def test_json_invalido_descarta_texto_e_tenta_de_novo():
    from atlas.cerebro import Conversa

    class FluxoQuebrado(FluxoFalso):
        def __iter__(self):
            yield SimpleNamespace(type="text", text="Vou anotar")
            raise ValueError("JSON inválido")

    cliente = ClienteFalso([FluxoQuebrado([], None), _texto("Pronto.")])
    eventos = list(Conversa(cliente).responder("Oi"))
    assert {"tipo": "descartar", "texto": "Vou anotar"} in eventos
    assert eventos[-1] == {"tipo": "texto", "texto": "Pronto."}


def test_entrada_invalida_da_ferramenta_vira_erro():
    from atlas.cerebro import _executar_ferramenta

    assert _executar_ferramenta("guardar_memoria", {"fato": ""})[1] is True
    assert _executar_ferramenta("guardar_memoria", "texto")[1] is True
    assert _executar_ferramenta("inexistente", {})[1] is True


def test_sem_chave_avisa():
    from atlas.cerebro import Conversa

    eventos = list(Conversa().responder("Oi"))
    assert eventos[0]["tipo"] == "erro" and "chave" in eventos[0]["texto"]


# ---------- servidor ----------

def _web():
    from atlas.servidor import app

    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_servidor_pagina_e_estado():
    web = _web()
    assert "ATLAS" in web.get("/").text
    estado = web.get("/api/estado").json()
    assert estado["tem_chave"] is False and estado["memoria"] == [] and estado["pasta"]
    assert web.post("/api/chave", json={"chave": "errada"}).status_code == 400
    assert web.post("/api/chave", json={"chave": "sk-ant-x"}).json() == {"ok": True}
    assert web.get("/api/estado").json()["tem_chave"] is True


def test_servidor_recusa_outro_host():
    from atlas.servidor import app

    intruso = TestClient(app, base_url="http://site-malicioso.com:8765")
    assert intruso.get("/api/estado").status_code == 400
    assert intruso.post("/api/chave", json={"chave": "sk-ant-x"}).status_code == 400


def test_servidor_apaga_memoria_exata():
    from atlas import memoria

    memoria.guardar("Prefere café")
    memoria.guardar("Prefere café sem açúcar")
    web = _web()
    assert web.delete("/api/memoria", params={"trecho": " "}).status_code == 400
    web.delete("/api/memoria", params={"trecho": "Prefere café", "exato": "true"})
    assert [f["fato"] for f in memoria.listar()] == ["Prefere café sem açúcar"]


def test_servidor_chat_transmite_eventos(monkeypatch):
    from atlas import servidor
    from atlas.cerebro import Conversa

    monkeypatch.setattr(servidor, "Conversa", lambda: Conversa(ClienteFalso([_texto("Olá")])))
    corpo = _web().post("/api/chat", json={"texto": "Oi"}).text
    assert '"tipo": "conversa"' in corpo
    assert '"texto": "Olá"' in corpo
    assert '"tipo": "fim"' in corpo


def test_servidor_avisa_conversa_reiniciada(monkeypatch):
    from atlas import servidor
    from atlas.cerebro import Conversa

    monkeypatch.setattr(servidor, "Conversa", lambda: Conversa(ClienteFalso([_texto("Olá")])))
    corpo = _web().post("/api/chat", json={"conversa": "id-que-sumiu", "texto": "Oi"}).text
    assert '"reiniciada": true' in corpo


def test_servidor_erro_inesperado_fecha_o_fluxo(monkeypatch):
    from atlas import servidor

    class Quebrada:
        def responder(self, texto):
            raise RuntimeError("bug")
            yield  # pragma: no cover

    monkeypatch.setattr(servidor, "Conversa", Quebrada)
    corpo = _web().post("/api/chat", json={"texto": "Oi"}).text
    assert "Erro inesperado" in corpo and '"tipo": "fim"' in corpo


# ---------- casos raros que não podem quebrar a conversa ----------

def test_recusa_no_meio_apaga_o_texto_da_tela():
    from atlas.cerebro import Conversa

    recusa = (["Parte da resposta"], SimpleNamespace(stop_reason="refusal", content=[Bloco(type="text", text="Parte da resposta")]))
    conversa = Conversa(ClienteFalso([recusa]))
    eventos = list(conversa.responder("Oi"))
    assert eventos[-2] == {"tipo": "descartar", "texto": "Parte da resposta"}
    assert eventos[-1]["tipo"] == "erro"
    assert conversa.mensagens == []


def test_falha_ao_gravar_memoria_vira_erro_da_ferramenta(monkeypatch):
    from atlas import memoria
    from atlas.cerebro import Conversa

    def trava(_):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(memoria, "_gravar", trava)
    conversa = Conversa(ClienteFalso([_uso_memoria(), _texto("Não consegui guardar.")]))
    eventos = list(conversa.responder("Lembre disso"))
    assert eventos[-1] == {"tipo": "texto", "texto": "Não consegui guardar."}
    resultado = conversa.mensagens[2]["content"][0]
    assert resultado["is_error"] is True and resultado["content"] == memoria.ERRO_GRAVACAO
    _historico_valido(conversa.mensagens)


def test_excecao_inesperada_desfaz_a_pergunta(monkeypatch):
    from atlas import cerebro
    from atlas.cerebro import Conversa

    conversa = Conversa(ClienteFalso([_texto("Oi."), _uso_memoria(), _texto("Ok.")]))
    list(conversa.responder("Oi"))
    monkeypatch.setattr(cerebro, "_executar_ferramenta", lambda *a: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        list(conversa.responder("Lembre disso"))
    assert len(conversa.mensagens) == 2
    _historico_valido(conversa.mensagens)


def test_tela_fechada_no_meio_desfaz_a_pergunta():
    from atlas.cerebro import Conversa

    conversa = Conversa(ClienteFalso([(["a", "b"], SimpleNamespace(stop_reason="end_turn", content=[Bloco(type="text", text="ab")]))]))
    gerador = conversa.responder("Oi")
    next(gerador)
    gerador.close()
    assert conversa.mensagens == []


def test_resposta_vazia_nao_entra_no_historico():
    from atlas.cerebro import Conversa

    vazia = ([], SimpleNamespace(stop_reason="end_turn", content=[]))
    conversa = Conversa(ClienteFalso([_texto("Oi."), vazia, _texto("Agora sim.")]))
    list(conversa.responder("Oi"))
    assert list(conversa.responder("de novo"))[-1]["tipo"] == "erro"
    assert list(conversa.responder("mais uma"))[-1] == {"tipo": "texto", "texto": "Agora sim."}
    _historico_valido(conversa.mensagens)


def test_pesquisa_cortada_sem_resultado_sai_do_historico():
    from atlas.cerebro import Conversa

    conteudo = [Bloco(type="text", text="Vou pesquisar"), Bloco(type="server_tool_use", id="srv1", name="web_search", input={})]
    cortada = (["Vou pesquisar"], SimpleNamespace(stop_reason="max_tokens", content=conteudo))
    conversa = Conversa(ClienteFalso([cortada]))
    list(conversa.responder("Oi"))
    assert [b["type"] for b in conversa.mensagens[1]["content"]] == ["text"]


def test_pausa_mantem_pesquisa_em_andamento():
    from atlas.cerebro import Conversa

    conteudo = [Bloco(type="server_tool_use", id="srv1", name="web_search", input={"query": "x"})]
    pausa = ([], SimpleNamespace(stop_reason="pause_turn", content=conteudo))
    cliente = ClienteFalso([pausa, _texto("Achei.")])
    conversa = Conversa(cliente)
    list(conversa.responder("Pesquise x"))
    assert cliente.chamadas[1]["messages"][-1]["content"][0]["type"] == "server_tool_use"


def test_outro_fim_com_ferramenta_pendente_fecha_a_ferramenta():
    from atlas.cerebro import Conversa

    uso = Bloco(type="tool_use", id="t5", name="guardar_memoria", input={"fato": "x"})
    cheio = ([], SimpleNamespace(stop_reason="model_context_window_exceeded", content=[uso]))
    conversa = Conversa(ClienteFalso([cheio]))
    assert list(conversa.responder("Oi"))[-1] == {"tipo": "erro", "texto": CONVERSA_LONGA}
    _historico_valido(conversa.mensagens)


def test_conversa_longa_demais_pede_nova_conversa():
    from atlas.cerebro import Conversa

    resposta = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com"))
    longa = anthropic.BadRequestError(
        "too long", response=resposta,
        body={"error": {"type": "invalid_request_error", "message": "prompt is too long: 1000001 tokens"}},
    )
    sem_credito = anthropic.BadRequestError(
        "credit", response=resposta,
        body={"error": {"type": "invalid_request_error", "message": "Your credit balance is too low"}},
    )
    assert list(Conversa(ClienteFalso([longa])).responder("Oi"))[-1]["texto"] == CONVERSA_LONGA
    assert "credit balance" in list(Conversa(ClienteFalso([sem_credito])).responder("Oi"))[-1]["texto"]


def test_transmissao_incompleta_e_tratada_como_queda():
    from atlas.cerebro import Conversa

    incompleta = (["meio"], SimpleNamespace(stop_reason=None, content=[Bloco(type="text", text="meio")]))
    conversa = Conversa(ClienteFalso([incompleta]))
    eventos = list(conversa.responder("Oi"))
    assert eventos[-1]["tipo"] == "erro" and "conexão" in eventos[-1]["texto"]
    assert conversa.mensagens == []


def test_json_invalido_repetido_desiste():
    from atlas.cerebro import Conversa

    class FluxoQuebrado(FluxoFalso):
        def __iter__(self):
            raise ValueError("JSON inválido")
            yield  # pragma: no cover

    conversa = Conversa(ClienteFalso([FluxoQuebrado([], None) for _ in range(3)]))
    eventos = list(conversa.responder("Oi"))
    assert "inválida" in eventos[-1]["texto"]
    assert conversa.mensagens == []


def test_sobrecarga_no_meio_nao_mostra_erro_200():
    from atlas.cerebro import Conversa

    resposta = httpx2.Response(200, request=httpx2.Request("POST", "https://api.anthropic.com"))
    erro = anthropic.APIStatusError("overloaded", response=resposta, body={"error": {"type": "overloaded_error"}})
    eventos = list(Conversa(ClienteFalso([erro])).responder("Oi"))
    assert "sobrecarregado" in eventos[-1]["texto"]


def test_textos_de_voltas_diferentes_ficam_separados():
    from atlas.cerebro import Conversa

    uso = Bloco(type="tool_use", id="t1", name="guardar_memoria", input={"fato": "Treina cedo"})
    volta1 = (["Vou guardar."], SimpleNamespace(stop_reason="tool_use", content=[Bloco(type="text", text="Vou guardar."), uso]))
    eventos = list(Conversa(ClienteFalso([volta1, _texto("Pronto.")])).responder("Lembre"))
    assert "".join(e["texto"] for e in eventos if e["tipo"] == "texto") == "Vou guardar.\n\nPronto."


def test_item_estranho_na_memoria_nao_derruba_o_atlas():
    from atlas import memoria
    from atlas.cerebro import mensagem_de_abertura
    from atlas.config import pasta_dados

    (pasta_dados() / "memoria.json").write_text('["Prefere café"]', encoding="utf-8")
    assert "(memória vazia)" in mensagem_de_abertura()
    assert memoria.guardar("x") == memoria.ERRO_LEITURA
    (pasta_dados() / "memoria.json").write_text('[{"fato": "Sem data"}]', encoding="utf-8")
    assert "Sem data" in mensagem_de_abertura()


def test_servidor_recusa_pedido_de_outro_site():
    web = _web()
    resposta = web.post("/api/chave", json={"chave": "sk-ant-ataque"}, headers={"Origin": "https://site-malicioso.com"})
    assert resposta.status_code == 403
    from atlas.config import ler_chave

    assert ler_chave() is None
    assert web.post("/api/chave", json={"chave": "sk-ant-x"}, headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200


# ---------- definição da IA (pasta ia/) ----------

def _ia(tmp_path_factory=None):
    from atlas.especialidade import pasta_ia

    pasta = pasta_ia()
    (pasta / "conhecimento").mkdir(parents=True, exist_ok=True)
    return pasta


def test_sem_pasta_ia_usa_instrucoes_padrao():
    from atlas import especialidade
    from atlas.persona import SISTEMA

    assert especialidade.sistema() == [{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}}]
    assert "allowed_domains" not in especialidade.pesquisa_web()


def test_instrucoes_documentos_e_fontes_da_pasta_ia():
    from atlas import especialidade

    pasta = _ia()
    (pasta / "instrucoes.md").write_text("<!-- anotação -->\nVocê é especialista em X.", encoding="utf-8")
    (pasta / "conhecimento" / "lei.txt").write_text("Art. 1º Regra.", encoding="utf-8")
    (pasta / "conhecimento" / "LEIA-ME.txt").write_text("não vai", encoding="utf-8")
    (pasta / "conhecimento" / "foto.png").write_bytes(b"x")
    (pasta / "fontes.txt").write_text("# comentário\nhttps://www.planalto.gov.br/x\nwww.gov.br\n", encoding="utf-8")
    blocos = especialidade.sistema()
    assert blocos[0] == {"type": "text", "text": "Você é especialista em X."}
    assert '<documento nome="lei.txt">' in blocos[1]["text"] and "não vai" not in blocos[1]["text"]
    assert blocos[1]["cache_control"] == {"type": "ephemeral"}
    assert especialidade.pesquisa_web()["allowed_domains"] == ["www.planalto.gov.br", "www.gov.br"]
    assert especialidade.resumo()["documentos"] == 1


def test_documentos_grandes_demais_ficam_de_fora(monkeypatch):
    from atlas import especialidade

    pasta = _ia()
    monkeypatch.setattr(especialidade, "LIMITE_DOCUMENTOS", 10)
    (pasta / "conhecimento" / "a.txt").write_text("12345", encoding="utf-8")
    (pasta / "conhecimento" / "b.txt").write_text("1234567890", encoding="utf-8")
    texto, fora = especialidade.documentos()
    assert 'nome="a.txt"' in texto and fora == ["b.txt"]


def test_cerebro_usa_a_definicao_da_ia():
    from atlas.cerebro import Conversa

    pasta = _ia()
    (pasta / "instrucoes.md").write_text("Você é o Bot X.", encoding="utf-8")
    (pasta / "fontes.txt").write_text("www.gov.br", encoding="utf-8")
    cliente = ClienteFalso([_texto("Oi.")])
    list(Conversa(cliente).responder("Oi"))
    chamada = cliente.chamadas[0]
    assert chamada["system"][0]["text"] == "Você é o Bot X."
    assert chamada["tools"][0]["allowed_domains"] == ["www.gov.br"]
    assert [t["name"] for t in chamada["tools"]] == ["web_search", "guardar_memoria", "esquecer_memoria"]


def test_robo_de_atualizacao_baixa_paginas():
    from atlas import atualizar

    pasta = _ia()
    (pasta / "atualizar.txt").write_text(
        "# exemplo\nNotícias Receita | https://exemplo.gov.br/noticias\nquebrada | https://exemplo.gov.br/404\n",
        encoding="utf-8",
    )

    def rota(pedido):
        if pedido.url.path == "/404":
            return httpx2.Response(404)
        html = "<html><script>x()</script><h1>Nova regra</h1><p>Vale a partir de 2027.</p></html>"
        return httpx2.Response(200, html=html)

    relatorio = atualizar.atualizar(httpx2.Client(transport=httpx2.MockTransport(rota)))
    assert relatorio[0].startswith("OK") and relatorio[1].startswith("FALHOU")
    salvo = (pasta / "conhecimento" / "atualizacoes" / "noticias-receita.md").read_text(encoding="utf-8")
    assert "Nova regra" in salvo and "Vale a partir de 2027." in salvo and "x()" not in salvo
    assert "Fonte: https://exemplo.gov.br/noticias" in salvo


def test_teste_com_perguntas_reais_gera_relatorio():
    import json

    from atlas import avaliar

    pasta = _ia()
    (pasta / "perguntas_teste.json").write_text(json.dumps([
        {"pergunta": "Qual o prazo?", "resposta_esperada": "Dia 20."},
        {"pergunta": "E o outro?", "resposta_esperada": "Dia 31."},
    ]), encoding="utf-8")
    cliente = ClienteFalso([_texto("Vence dia 20."), _texto("Vence dia 10.")])
    notas = iter(["CERTO\nBateu.", "ERRADO\nDisse 10, esperado 31."])
    cliente.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="text", text=next(notas))]))
    resumo = avaliar.avaliar(cliente)
    assert resumo.startswith("Acertos: 1 de 2")
    relatorio = (pasta / "resultado_teste.md").read_text(encoding="utf-8")
    assert "✅ CERTO" in relatorio and "❌ ERRADO" in relatorio and "Vence dia 10." in relatorio


# ---------- revisão da carcaça ----------

def test_arquivos_salvos_em_ansi_ou_utf16_sao_lidos_certo():
    from atlas import especialidade

    pasta = _ia()
    (pasta / "instrucoes.md").write_bytes("Você é especialista em legislação.".encode("cp1252"))
    (pasta / "conhecimento" / "lei.txt").write_bytes("Art. 1º A alíquota é de 12% (§ 2º).".encode("cp1252"))
    (pasta / "conhecimento" / "tabela.txt").write_text("Produto\tAlíquota", encoding="utf-16")
    (pasta / "fontes.txt").write_bytes("# Fontes (legislação)\nwww.gov.br".encode("cp1252"))
    assert especialidade.instrucoes() == "Você é especialista em legislação."
    texto, _ = especialidade.documentos()
    assert "Art. 1º A alíquota é de 12% (§ 2º)." in texto and "Produto\tAlíquota" in texto
    assert especialidade.dominios() == ["www.gov.br"]


def test_linhas_definir_sao_ignoradas_ate_serem_preenchidas():
    from atlas import especialidade

    pasta = _ia()
    (pasta / "instrucoes.md").write_text(
        "<!-- nota -->\nVocê é o Atlas.\n"
        "[DEFINIR] Especialidade: escreva aqui qual problema a IA resolve. Ex.: Você é especialista em ...\n"
        "[DEFINIR] Público: Você atende contadores.\n",
        encoding="utf-8",
    )
    texto = especialidade.instrucoes()
    assert texto == "Você é o Atlas.\nPúblico: Você atende contadores."
    assert especialidade.pendentes() == 1


def test_modelo_de_instrucoes_do_repositorio_funciona(monkeypatch):
    from pathlib import Path

    from atlas import especialidade

    monkeypatch.setenv("ATLAS_IA", str(Path(__file__).resolve().parent.parent / "ia"))
    texto = especialidade.instrucoes()
    assert texto.startswith("Você é o Atlas") and "DEFINIR" not in texto and "<!--" not in texto
    assert especialidade.pendentes() == 6
    assert especialidade.dominios() == []


def test_fontes_invalidas_sao_ignoradas_e_avisadas():
    from atlas import especialidade

    pasta = _ia()
    (pasta / "fontes.txt").write_text(
        "gov.br\njus.br\nhttps://www.planalto.gov.br/ccivil_03/a.htm\nhttps://www.planalto.gov.br/b\n"
        "planalto.gov.br  # leis federais\nlocalhost:8000\n192.168.0.1\nstf.jus.br:443/x\n",
        encoding="utf-8",
    )
    aceitos, recusados = especialidade.fontes()
    assert aceitos == ["www.planalto.gov.br", "planalto.gov.br", "stf.jus.br"]
    assert recusados == ["gov.br", "jus.br", "localhost:8000", "192.168.0.1"]
    assert especialidade.resumo()["fontes_recusadas"] == recusados


def test_definicao_fica_fixa_durante_a_conversa():
    from atlas.cerebro import Conversa

    pasta = _ia()
    (pasta / "instrucoes.md").write_text("Versão 1.", encoding="utf-8")
    cliente = ClienteFalso([_texto("a"), _texto("b"), _texto("c")])
    conversa = Conversa(cliente)
    list(conversa.responder("Oi"))
    (pasta / "instrucoes.md").write_text("Versão 2.", encoding="utf-8")
    list(conversa.responder("De novo"))
    assert [c["system"][0]["text"] for c in cliente.chamadas] == ["Versão 1.", "Versão 1."]
    nova = Conversa(cliente)
    list(nova.responder("Oi"))
    assert cliente.chamadas[-1]["system"][0]["text"] == "Versão 2."


def test_pasta_ia_ilegivel_da_mensagem_clara(monkeypatch):
    from atlas import especialidade
    from atlas.cerebro import Conversa

    def quebra():
        raise PermissionError("acesso negado")

    monkeypatch.setattr(especialidade, "sistema", quebra)
    conversa = Conversa(ClienteFalso([]))
    eventos = list(conversa.responder("Oi"))
    assert eventos == [{"tipo": "erro", "texto": "Não consegui ler a pasta ia/ (definição da IA): acesso negado"}]
    assert conversa.mensagens == []


def test_estado_responde_mesmo_com_pasta_ia_quebrada(monkeypatch):
    from atlas import especialidade

    def quebra():
        raise PermissionError("acesso negado")

    monkeypatch.setattr(especialidade, "documentos", quebra)
    resposta = _web().get("/api/estado")
    assert resposta.status_code == 200 and "acesso negado" in resposta.json()["ia"]["erro"]


def test_erro_de_site_recusado_pelo_claude_explica_o_que_fazer():
    from atlas.cerebro import _mensagem_erro_api

    resposta = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com"))
    erro = anthropic.BadRequestError("x", response=resposta, body={"error": {
        "type": "invalid_request_error", "message": "tools.0.allowed_domains: 'co.uk' is a public suffix"}})
    assert "ia/fontes.txt" in _mensagem_erro_api(erro)


def _robo(pasta, rota):
    from atlas import atualizar

    return atualizar.atualizar(httpx2.Client(transport=httpx2.MockTransport(rota)))


def test_robo_ignora_pdf_e_avisa():
    pasta = _ia()
    (pasta / "atualizar.txt").write_text("lei | https://exemplo.gov.br/lei.pdf\n", encoding="utf-8")
    relatorio = _robo(pasta, lambda r: httpx2.Response(200, content=b"%PDF-1.7 ...", headers={"Content-Type": "application/pdf"}))
    assert relatorio[0].startswith("IGNORADO") and "PDF" in relatorio[0]
    assert not (pasta / "conhecimento" / "atualizacoes" / "lei.md").exists()


def test_robo_mantem_acentos_de_pagina_antiga_em_windows_1252():
    pasta = _ia()
    (pasta / "atualizar.txt").write_text("lei | https://www.planalto.gov.br/lei.htm\n", encoding="utf-8")
    html = '<html><meta http-equiv="Content-Type" content="text/html; charset=windows-1252"><p>contribuição § 1º</p></html>'
    _robo(pasta, lambda r: httpx2.Response(200, content=html.encode("cp1252"), headers={"Content-Type": "text/html"}))
    salvo = (pasta / "conhecimento" / "atualizacoes" / "lei.md").read_text(encoding="utf-8")
    assert "contribuição § 1º" in salvo


def test_robo_avisa_pagina_cortada(monkeypatch):
    from atlas import atualizar

    pasta = _ia()
    monkeypatch.setattr(atualizar, "LIMITE_POR_PAGINA", 10)
    (pasta / "atualizar.txt").write_text("grande | https://exemplo.gov.br/g\n", encoding="utf-8")
    relatorio = _robo(pasta, lambda r: httpx2.Response(200, text="x" * 50))
    assert "guardei só o começo" in relatorio[0]
    assert "página cortada" in (pasta / "conhecimento" / "atualizacoes" / "grande.md").read_text(encoding="utf-8")


def test_teste_nao_mexe_na_memoria_real():
    import json

    from atlas import avaliar, memoria

    memoria.guardar("Fato real do usuário")
    pasta = _ia()
    (pasta / "perguntas_teste.json").write_text(json.dumps([
        {"pergunta": "Sou MEI", "resposta_esperada": "Ok."},
        {"pergunta": "E agora?", "resposta_esperada": "Ok."},
    ]), encoding="utf-8")
    cliente = ClienteFalso([_uso_memoria("O usuário é MEI"), _texto("Ok."), _texto("Ok.")])
    cliente.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="CERTO\nok")]))
    avaliar.avaliar(cliente)
    assert [f["fato"] for f in memoria.listar()] == ["Fato real do usuário"]
    assert "(memória vazia)" in cliente.chamadas[-1]["messages"][0]["content"]


def test_falha_do_avaliador_nao_para_o_teste():
    import json

    from atlas import avaliar

    pasta = _ia()
    (pasta / "perguntas_teste.json").write_text(json.dumps([
        {"pergunta": "A?", "resposta_esperada": "a"}, {"pergunta": "B?", "resposta_esperada": "b"},
        {"pergunta": "sem resposta esperada"},
    ]), encoding="utf-8")
    cliente = ClienteFalso([_texto("a"), _texto("b")])
    chamadas = iter([anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), None])

    def julgar(**kw):
        erro = next(chamadas)
        if erro:
            raise erro
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="CERTO\nok")])

    cliente.messages = SimpleNamespace(create=julgar)
    resumo = avaliar.avaliar(cliente)
    assert resumo.startswith("Acertos: 1 de 1, 1 não avaliada(s), 1 ignorada(s)")
    assert "⚠️ NÃO AVALIADO" in (pasta / "resultado_teste.md").read_text(encoding="utf-8")


def test_erro_de_digitacao_no_json_explica_onde():
    from atlas import avaliar

    pasta = _ia()
    (pasta / "perguntas_teste.json").write_text('[{"pergunta": "A?" "resposta_esperada": "a"}]', encoding="utf-8")
    resumo = avaliar.avaliar(ClienteFalso([]))
    assert "linha 1" in resumo and "Confira aspas" in resumo


# ---------- conferência final ----------

def test_texto_utf8_com_um_byte_estranho_mantem_os_acentos():
    from atlas.especialidade import decodificar

    dados = "Art. 1º A contribuição é de 12%; alíquota § 2º. ".encode("utf-8") * 5 + b"caf\xe9"
    texto = decodificar(dados)
    assert "contribuição" in texto and "Ã" not in texto


def test_fontes_sem_nenhum_site_valido_desligam_a_pesquisa_e_avisam():
    from atlas import especialidade
    from atlas.cerebro import Conversa

    pasta = _ia()
    (pasta / "fontes.txt").write_text("gov.br\njus.br\n", encoding="utf-8")
    assert especialidade.pesquisa_web() is None
    cliente = ClienteFalso([_texto("Oi.")])
    eventos = list(Conversa(cliente).responder("Oi"))
    assert eventos[0]["tipo"] == "aviso" and "desligada" in eventos[0]["texto"]
    assert [t["name"] for t in cliente.chamadas[0]["tools"]] == ["guardar_memoria", "esquecer_memoria"]
    assert especialidade.resumo()["pesquisa_desligada"] is True


def test_fontes_em_lista_com_marcadores_e_rotulos():
    from atlas import especialidade

    pasta = _ia()
    (pasta / "fontes.txt").write_text(
        "- www.planalto.gov.br\n* stf.jus.br\n1. www.gov.br\nReceita: receita.fazenda.gov.br\n"
        "sp.gov.br\nintranet.empresa.local\n127.1\n",
        encoding="utf-8",
    )
    aceitos, recusados = especialidade.fontes()
    assert aceitos == ["www.planalto.gov.br", "stf.jus.br", "www.gov.br", "receita.fazenda.gov.br"]
    assert recusados == ["sp.gov.br", "intranet.empresa.local", "127.1"]


def test_robo_aceita_feed_rss_e_respeita_meta_charset():
    pasta = _ia()
    (pasta / "atualizar.txt").write_text(
        "feed | https://exemplo.gov.br/rss\npagina | https://exemplo.gov.br/p\n", encoding="utf-8")

    def rota(pedido):
        if pedido.url.path == "/rss":
            return httpx2.Response(200, content="<rss><item>Nova regra</item></rss>".encode(),
                                   headers={"Content-Type": "application/rss+xml"})
        html = '<html><meta charset="utf-8"><p>contribuição alíquota</p><p>caf\xe9</p></html>'
        corpo = html.encode("utf-8").replace("caf\xe9".encode("utf-8"), b"caf\xe9")
        return httpx2.Response(200, content=corpo, headers={"Content-Type": "text/html"})

    relatorio = _robo(pasta, rota)
    assert relatorio[0].startswith("OK") and relatorio[1].startswith("OK")
    pagina = (pasta / "conhecimento" / "atualizacoes" / "pagina.md").read_text(encoding="utf-8")
    assert "contribuição alíquota" in pagina


def test_relatorio_do_robo_fica_guardado_e_aparece_em_configurar():
    from atlas import atualizar, especialidade

    _ia()
    atualizar.gravar_relatorio(["OK      a: 10 caracteres", "FALHOU  b: 404"])
    assert "1 página(s) atualizada(s), 1 com falha" in especialidade.resumo()["robo"]
    texto, _ = especialidade.documentos()
    assert "_ultimo_relatorio" not in texto


def test_falha_do_claude_ao_responder_nao_conta_como_erro():
    import json

    from atlas import avaliar

    pasta = _ia()
    (pasta / "perguntas_teste.json").write_text(json.dumps([
        {"pergunta": "A?", "resposta_esperada": "a"},
        {"pergunta": None, "resposta_esperada": "x"},
        {"pergunta": "C?", "resposta_esperada": None},
    ]), encoding="utf-8")
    resposta = httpx2.Response(429, request=httpx2.Request("POST", "https://api.anthropic.com"))
    cliente = ClienteFalso([anthropic.RateLimitError("limite", response=resposta, body=None)])
    resumo = avaliar.avaliar(cliente)
    assert resumo.startswith("Acertos: 0 de 0, 1 não avaliada(s), 2 ignorada(s)")


def test_avaliador_com_veredito_e_motivo_na_mesma_linha_ou_cortado():
    from atlas import avaliar

    def cliente(texto, parada="end_turn"):
        return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            stop_reason=parada, content=[SimpleNamespace(type="text", text=texto)])))

    assert avaliar.julgar(cliente("ERRADO — disse 10, esperado 31."), "p", "e", "r") == (False, "disse 10, esperado 31.")
    assert avaliar.julgar(cliente("**CERTO**\nbateu"), "p", "e", "r") == (True, "bateu")
    assert avaliar.julgar(cliente("ERRADO", "max_tokens"), "p", "e", "r")[0] is None
