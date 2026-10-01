# script-key — Analisador Universal de Scripts

Recebeu um script e não sabe como rodar? Informe o arquivo e o **script-key** diz:

- **qual linguagem** o script usa;
- **o que precisa estar instalado** (e se já está no seu computador);
- **o comando exato** para copiar e colar no terminal — adaptado para Windows, Linux ou macOS.

Só precisa do Python 3.8+ — nenhuma biblioteca extra.

## Como usar

```bash
python analisador_scripts.py caminho/do/script.sh
```

Pode passar vários arquivos de uma vez, ou rodar sem argumentos para ele perguntar o caminho
(no Windows, dá para arrastar o arquivo para a janela do terminal).

Exemplo de saída no Linux:

```
============================================================
 Arquivo:      deploy.sh
 Sistema:      Linux
 Linguagem:    Shell Script (Bash)  (detectada por extensão .sh)
 Requisito:    Bash
 Instalado em: /usr/bin/bash
------------------------------------------------------------
 Copie e cole no terminal:

   chmod +x deploy.sh
   ./deploy.sh
============================================================
```

## Como ele descobre a linguagem

1. **Extensão do arquivo** — `.py`, `.js`, `.ts`, `.sh`, `.ps1`, `.bat`, `.cmd`, `.rb`, `.pl`, `.php`,
   `.lua`, `.r`, `.go`, `.java`, `.kts`, `.swift`, `.jl`, `.dart`, `.exs`, `.vbs`, `.applescript` e outras.
2. **Shebang** — se não houver extensão, lê a primeira linha (`#!/bin/bash`, `#!/usr/bin/env node`,
   `#!/usr/bin/python3.11`…).
3. **Pistas no conteúdo** — `<?php` ou `@echo off` no início do arquivo.

## Regras por sistema

| Situação | O que o script-key sugere |
|---|---|
| Script de shell no Linux/macOS | `chmod +x` (se ainda não tiver permissão) e `./script.sh` |
| Script de shell no Windows | `bash script.sh` (Git Bash ou WSL) |
| PowerShell no Windows | `powershell -ExecutionPolicy Bypass -File script.ps1` |
| Python no Windows | `py script.py` (o lançador oficial), ou `python` se o `py` não existir |
| `.bat`/`.vbs` fora do Windows, AppleScript fora do macOS | Avisa que não roda nesse sistema |
| Interpretador não instalado | Mostra o comando mesmo assim e o link para instalar |

Também avisa quando o arquivo não existe, é uma pasta ou é um **binário** (programa compilado),
que não pode ser lido como script.

## Testes

```bash
pip install pytest
python -m pytest
```
