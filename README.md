# Atlas — assistente de IA

O Atlas é uma inteligência artificial com a personalidade de um braço direito estratégico.
Ele é separado do Jarvis: tem pasta, memória e chave próprias.
O cérebro é o **Claude** (Anthropic), e a conversa acontece numa tela de chat no navegador.

## O que ele faz

- Conversa sobre qualquer assunto, com profundidade em governança familiar, holdings,
  sucessão, M&A, contabilidade, tributação (inclusive Reforma Tributária) e gestão.
- Escreve e-mails, propostas, posts e discursos na sua voz.
- Pesquisa na web quando o assunto depende de informação atual, e cita as fontes.
- Lembra do que você pede: "Atlas, lembre que o minhas reuniões são sempre às 9h".
  Para ver ou apagar o que ele lembra, use **⚙ Configurar**.

## Instalação no Windows

1. Baixe o projeto (botão verde **Code → Download ZIP**) e extraia a pasta.
2. Dê dois cliques em **`Iniciar Atlas`**.
   - Se o Windows avisar "O Windows protegeu o computador", clique em **Mais informações → Executar assim mesmo**.
   - Se o Python não estiver instalado, o Atlas instala sozinho. Depois é só abrir o `Iniciar Atlas` de novo.
   - Na primeira vez ele leva alguns minutos para se preparar.
3. O navegador abre sozinho no endereço `http://127.0.0.1:8765`.
4. Na primeira vez, cole a **chave da Anthropic**:
   - acesse https://console.anthropic.com/settings/keys, entre na conta e clique em **Create Key**;
   - copie a chave (começa com `sk-ant-`), cole no Atlas e clique em **Salvar chave**.

Para desligar, feche a janela preta do `Iniciar Atlas`.

> **Custos:** o Claude é pago por uso, na conta da Anthropic. Dá para definir um limite
> mensal de gastos em console.anthropic.com → Billing.
>
> **Privacidade:** a chave e a memória ficam na pasta `C:\Users\<seu usuário>\Documents\Atlas`,
> só no seu computador (é a pasta local, fora do OneDrive). O caminho exato aparece na janela
> preta ao iniciar e em **⚙ Configurar**. O Atlas não fica aberto na rede: só funciona nesse computador.

## Para programadores

| Arquivo | Função |
|---|---|
| `Iniciar Atlas.bat` | Cria o ambiente Python, instala as dependências e abre o Atlas |
| `atlas/__main__.py` | Sobe o servidor local e abre o navegador |
| `atlas/servidor.py` | API local (FastAPI): chat com streaming, chave e memória |
| `atlas/cerebro.py` | Conversa com o Claude: pesquisa na web, ferramentas de memória e fallback |
| `atlas/persona.py` | Quem o Atlas é (system prompt) |
| `atlas/memoria.py` | Memória de longo prazo (`Documents\Atlas\memoria.json`) |
| `atlas/config.py` | Pasta de dados, modelo e chave |
| `atlas/static/index.html` | Tela de chat |

```bash
pip install -r requirements.txt
python -m atlas                 # abre em http://127.0.0.1:8765
python -m pytest                # testes (pip install pytest httpx); não gastam créditos
```

Variáveis opcionais: `ATLAS_MODELO` (padrão `claude-opus-5-5`), `ATLAS_ESFORCO`
(`low`, `medium`, `high`, `xhigh` ou `max`; padrão `high`), `ATLAS_PASTA` e `ANTHROPIC_API_KEY`
(usada só quando nenhuma chave foi salva em ⚙ Configurar).
