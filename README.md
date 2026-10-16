# Atlas — assistente de IA

A **carcaça** de uma IA especializada: já tem cérebro (**Claude**), tela de chat no navegador,
pesquisa na web, memória, base de conhecimento, robô de atualização e teste de qualidade.
Falta só a **definição** (qual área, para quem, com quais documentos), que fica toda na pasta `ia/`.

## O que ele faz

- Conversa numa tela de chat no navegador e responde seguindo as instruções de `ia/instrucoes.md`.
- Consulta os documentos que você puser em `ia/conhecimento/` e cita de onde tirou a informação.
- Pesquisa na web quando o assunto depende de informação atual (em qualquer site, ou só nos sites de `ia/fontes.txt`).
- Lembra do que você pede: "Atlas, lembre que minhas reuniões são sempre às 9h".
  Para ver ou apagar o que ele lembra, use **⚙ Configurar**.

## Como definir a sua IA (as 6 fases)

Tudo fica na pasta **`ia/`**. Edite os arquivos com o Bloco de Notas; vale na próxima pergunta.

| Fase | Onde | O que fazer |
|---|---|---|
| **1. Definição** e **2. Personalidade** | `ia/instrucoes.md` | Preencha os trechos marcados com `[DEFINIR]`: especialidade, público, o que responde, o que não pode fazer, quando encaminhar para um humano, formato da resposta |
| **3. Base de conhecimento** | `ia/conhecimento/` | Coloque leis, manuais, perguntas frequentes e tabelas em `.txt` ou `.md` (PDF: copie o texto e salve como `.txt`) |
| **4. Sempre atual** | `ia/fontes.txt` e `ia/atualizar.txt` | Em `fontes.txt`, os sites oficiais onde a IA pode pesquisar. Em `atualizar.txt`, as páginas que o robô baixa para a base quando você roda **`Atualizar Base`** |
| **5. Canal** | — | Começa nesta tela de chat, no seu computador. Site ou WhatsApp vêm depois |
| **6. Teste** | `ia/perguntas_teste.json` | Escreva ~30 perguntas reais com a resposta certa e rode **`Testar IA`**. O resultado sai em `ia/resultado_teste.md`, com o que acertou e o que errou |

**Robô da madrugada:** para atualizar a base sozinho todo dia, abra o **Agendador de Tarefas**
do Windows → *Criar Tarefa Básica* → *Diariamente*, às 3h → *Iniciar um programa* → escolha o
`Atualizar Base.bat` desta pasta.

> O **Testar IA** gasta créditos da Anthropic: duas chamadas por pergunta (a resposta e a correção).

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
| `ia/` | A definição da IA (fases 1 a 6) |
| `atlas/__main__.py` | Sobe o servidor local e abre o navegador |
| `atlas/servidor.py` | API local (FastAPI): chat com streaming, chave e memória |
| `atlas/cerebro.py` | Conversa com o Claude: pesquisa na web, ferramentas de memória e fallback |
| `atlas/especialidade.py` | Lê a pasta `ia/`: instruções, documentos e fontes |
| `atlas/atualizar.py` | Robô de atualização (`Atualizar Base.bat`) |
| `atlas/avaliar.py` | Teste com perguntas reais (`Testar IA.bat`) |
| `atlas/persona.py` | Instruções padrão, usadas se `ia/instrucoes.md` não existir |
| `atlas/memoria.py` | Memória de longo prazo (`Documents\Atlas\memoria.json`) |
| `atlas/config.py` | Pasta de dados, modelo e chave |
| `atlas/static/index.html` | Tela de chat |

```bash
pip install -r requirements.txt
python -m atlas                 # abre em http://127.0.0.1:8765
python -m pytest                # testes (pip install pytest httpx); não gastam créditos
```

Variáveis opcionais: `ATLAS_MODELO` (padrão `claude-opus-5-5`), `ATLAS_ESFORCO`
(`low`, `medium`, `high`, `xhigh` ou `max`; padrão `high`), `ATLAS_PASTA`, `ATLAS_IA` (outra pasta de definição) e `ANTHROPIC_API_KEY`
(usada só quando nenhuma chave foi salva em ⚙ Configurar).
