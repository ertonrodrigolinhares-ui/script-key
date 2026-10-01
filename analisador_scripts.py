#!/usr/bin/env python3
"""Analisador Universal de Scripts.

Recebe o caminho de um script qualquer e diz:
  - qual linguagem ele usa;
  - o que precisa estar instalado para rodá-lo;
  - o comando exato para executá-lo no sistema atual (Windows, Linux ou macOS).

Uso:
    python analisador_scripts.py caminho/do/script [outro/script ...]
    python analisador_scripts.py            (pergunta o caminho)

Só usa a biblioteca padrão do Python (3.8+).
"""

import os
import platform
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Catálogo de linguagens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Linguagem:
    nome: str
    requisito: str                       # o que o usuário precisa ter instalado
    unix: Tuple[str, ...] = ()           # interpretadores possíveis no Linux/macOS, em ordem de preferência
    windows: Tuple[str, ...] = ()        # interpretadores possíveis no Windows
    args_unix: Tuple[str, ...] = ()      # argumentos entre o interpretador e o arquivo
    args_windows: Tuple[str, ...] = ()
    shell_unix: bool = False             # no Unix roda direto (chmod +x e ./script)
    apenas: Optional[str] = None         # "windows" ou "macos" quando só roda nesse sistema
    instalar: str = ""                   # onde conseguir o interpretador


SHELL = Linguagem("Shell Script (Bash)", "Bash", unix=("bash",), windows=("bash",), shell_unix=True,
                  instalar="Windows: instale o Git for Windows (Git Bash) ou o WSL")
SH = Linguagem("Shell Script (sh)", "Shell POSIX (sh)", unix=("sh",), windows=("bash",), shell_unix=True,
               instalar="Windows: instale o Git for Windows (Git Bash) ou o WSL")
ZSH = Linguagem("Shell Script (Zsh)", "Zsh", unix=("zsh",), shell_unix=True, instalar="https://www.zsh.org")
KSH = Linguagem("Shell Script (Ksh)", "KornShell", unix=("ksh",), shell_unix=True)
FISH = Linguagem("Shell Script (Fish)", "Fish shell", unix=("fish",), shell_unix=True, instalar="https://fishshell.com")
PYTHON = Linguagem("Python", "Python 3", unix=("python3", "python"), windows=("py", "python", "python3"),
                   instalar="https://www.python.org/downloads")
NODE = Linguagem("JavaScript (Node.js)", "Node.js", unix=("node",), windows=("node",),
                 instalar="https://nodejs.org")
TYPESCRIPT = Linguagem("TypeScript", "Node.js + tsx (via npx) ou Deno", unix=("npx", "deno"),
                       windows=("npx", "deno"), args_unix=("tsx",), args_windows=("tsx",),
                       instalar="https://nodejs.org")
POWERSHELL = Linguagem("PowerShell", "PowerShell", unix=("pwsh",), windows=("powershell", "pwsh"),
                       args_unix=("-File",), args_windows=("-ExecutionPolicy", "Bypass", "-File"),
                       instalar="https://aka.ms/powershell")
BATCH = Linguagem("Batch do Windows (CMD)", "Prompt de Comando do Windows (cmd.exe)", windows=("cmd",),
                  args_windows=("/c",), apenas="windows")
VBSCRIPT = Linguagem("VBScript", "Windows Script Host (cscript)", windows=("cscript",),
                     args_windows=("//nologo",), apenas="windows")
APPLESCRIPT = Linguagem("AppleScript", "osascript (já vem no macOS)", unix=("osascript",), apenas="macos")
RUBY = Linguagem("Ruby", "Ruby", unix=("ruby",), windows=("ruby",), instalar="https://www.ruby-lang.org")
PERL = Linguagem("Perl", "Perl", unix=("perl",), windows=("perl",),
                 instalar="https://www.perl.org/get.html (no Windows: Strawberry Perl)")
PHP = Linguagem("PHP", "PHP (linha de comando)", unix=("php",), windows=("php",), instalar="https://www.php.net")
LUA = Linguagem("Lua", "Lua", unix=("lua",), windows=("lua",), instalar="https://www.lua.org")
R = Linguagem("R", "R (Rscript)", unix=("Rscript",), windows=("Rscript",), instalar="https://cran.r-project.org")
GO = Linguagem("Go", "Go", unix=("go",), windows=("go",), args_unix=("run",), args_windows=("run",),
               instalar="https://go.dev/dl")
JAVA = Linguagem("Java (arquivo único)", "Java JDK 11 ou superior", unix=("java",), windows=("java",),
                 instalar="https://adoptium.net")
KOTLIN = Linguagem("Kotlin Script", "Kotlin", unix=("kotlin",), windows=("kotlin",),
                   instalar="https://kotlinlang.org")
GROOVY = Linguagem("Groovy", "Groovy", unix=("groovy",), windows=("groovy",), instalar="https://groovy-lang.org")
SWIFT = Linguagem("Swift", "Swift", unix=("swift",), windows=("swift",), instalar="https://www.swift.org")
JULIA = Linguagem("Julia", "Julia", unix=("julia",), windows=("julia",), instalar="https://julialang.org")
DART = Linguagem("Dart", "Dart SDK", unix=("dart",), windows=("dart",), args_unix=("run",),
                 args_windows=("run",), instalar="https://dart.dev")
ELIXIR = Linguagem("Elixir", "Elixir", unix=("elixir",), windows=("elixir",), instalar="https://elixir-lang.org")
TCL = Linguagem("Tcl", "Tcl (tclsh)", unix=("tclsh",), windows=("tclsh",))
AWK = Linguagem("AWK", "awk", unix=("awk", "gawk"), windows=("gawk", "awk"), args_unix=("-f",),
                args_windows=("-f",))

# Extensão (em minúsculas) -> linguagem
POR_EXTENSAO: Dict[str, Linguagem] = {
    ".py": PYTHON, ".pyw": PYTHON,
    ".js": NODE, ".mjs": NODE, ".cjs": NODE,
    ".ts": TYPESCRIPT, ".mts": TYPESCRIPT,
    ".sh": SHELL, ".bash": SHELL, ".zsh": ZSH, ".ksh": KSH, ".fish": FISH,
    ".ps1": POWERSHELL,
    ".bat": BATCH, ".cmd": BATCH,
    ".vbs": VBSCRIPT,
    ".applescript": APPLESCRIPT, ".scpt": APPLESCRIPT,
    ".rb": RUBY, ".pl": PERL, ".pm": PERL, ".php": PHP, ".lua": LUA,
    ".r": R, ".go": GO, ".java": JAVA, ".kts": KOTLIN, ".groovy": GROOVY,
    ".swift": SWIFT, ".jl": JULIA, ".dart": DART, ".exs": ELIXIR,
    ".tcl": TCL, ".awk": AWK,
}

# Nome do interpretador no shebang -> linguagem
POR_SHEBANG: Dict[str, Linguagem] = {
    "bash": SHELL, "sh": SH, "dash": SH, "zsh": ZSH, "ksh": KSH, "fish": FISH,
    "python": PYTHON, "node": NODE, "nodejs": NODE, "deno": TYPESCRIPT, "pwsh": POWERSHELL,
    "ruby": RUBY, "perl": PERL, "php": PHP, "lua": LUA, "rscript": R, "groovy": GROOVY,
    "swift": SWIFT, "julia": JULIA, "elixir": ELIXIR, "tclsh": TCL, "awk": AWK, "gawk": AWK,
    "osascript": APPLESCRIPT,
}

NOMES_SISTEMA = {"windows": "Windows", "linux": "Linux", "macos": "macOS"}


# ---------------------------------------------------------------------------
# Projetos: quando o caminho é uma PASTA, descobre como preparar/compilar.
# São projetos genéricos (valem para qualquer código nessa tecnologia).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Projeto:
    nome: str                       # tipo de projeto
    requisito: str                  # o que precisa estar instalado
    ferramenta: str                 # programa de build, para checar com shutil.which ("" = não checa)
    passos: Tuple[str, ...]         # comandos de preparação/compilação, em ordem
    observacao: str = ""            # nota extra (ex.: no Windows precisa de WSL)
    instalar: str = ""              # onde conseguir a ferramenta


AUTOTOOLS = Projeto(
    "Projeto C/C++ (Autotools)", "Compilador C/C++ e make", "make",
    ("./configure", "make"),
    observacao=("Programa em C/C++ que precisa ser compilado. No Windows, compile pelo WSL, "
                "MSYS2 ou Cygwin. Depois rode o programa gerado (ex.: ./nome-do-programa --help)."),
    instalar="Linux: sudo apt install build-essential")
CMAKE = Projeto(
    "Projeto C/C++ (CMake)", "CMake e um compilador C/C++", "cmake",
    ("cmake -B build", "cmake --build build"),
    observacao="Depois de compilar, o programa fica na pasta 'build'.",
    instalar="https://cmake.org/download")
MAKE = Projeto(
    "Projeto com Makefile", "make e o compilador que o projeto usar", "make",
    ("make",),
    observacao="Leia o README do projeto; alguns Makefiles têm alvos como 'make install'.")
NODE_PROJ = Projeto(
    "Projeto Node.js", "Node.js", "npm",
    ("npm install", "npm start"),
    observacao="Se não houver 'start', veja os comandos em 'scripts' no arquivo package.json.",
    instalar="https://nodejs.org")
PYTHON_REQ = Projeto(
    "Projeto Python", "Python 3", "pip",
    ("pip install -r requirements.txt",),
    observacao="Depois, rode o arquivo principal, geralmente 'python main.py' ou 'python app.py'.",
    instalar="https://www.python.org/downloads")
PYTHON_PKG = Projeto(
    "Pacote Python", "Python 3", "pip",
    ("pip install .",),
    instalar="https://www.python.org/downloads")
RUST = Projeto(
    "Projeto Rust (Cargo)", "Rust e Cargo", "cargo",
    ("cargo run",),
    instalar="https://www.rust-lang.org/tools/install")
GO_PROJ = Projeto(
    "Projeto Go", "Go", "go",
    ("go build ./...",),
    observacao="Para rodar sem gerar o executável: 'go run .'.",
    instalar="https://go.dev/dl")
MAVEN = Projeto(
    "Projeto Java (Maven)", "Java JDK e Maven", "mvn",
    ("mvn package",),
    instalar="https://maven.apache.org")
GRADLE = Projeto(
    "Projeto Java (Gradle)", "Java JDK e Gradle", "gradle",
    ("gradle build",),
    instalar="https://gradle.org")
COMPOSER = Projeto(
    "Projeto PHP (Composer)", "PHP e Composer", "composer",
    ("composer install",),
    instalar="https://getcomposer.org")
BUNDLER = Projeto(
    "Projeto Ruby (Bundler)", "Ruby e Bundler", "bundle",
    ("bundle install",),
    instalar="https://bundler.io")

# Arquivo que marca o tipo de projeto (em minúsculas) -> projeto, em ordem de prioridade.
# Autotools/CMake vêm antes de 'Makefile' puro porque também costumam trazer um Makefile.
MARCADORES_PROJETO: Tuple[Tuple[str, Projeto], ...] = (
    ("configure", AUTOTOOLS), ("configure.ac", AUTOTOOLS), ("autogen.sh", AUTOTOOLS),
    ("cmakelists.txt", CMAKE),
    ("package.json", NODE_PROJ),
    ("cargo.toml", RUST),
    ("go.mod", GO_PROJ),
    ("pom.xml", MAVEN),
    ("build.gradle", GRADLE), ("build.gradle.kts", GRADLE),
    ("composer.json", COMPOSER),
    ("gemfile", BUNDLER),
    ("requirements.txt", PYTHON_REQ),
    ("pyproject.toml", PYTHON_PKG), ("setup.py", PYTHON_PKG),
    ("makefile", MAKE), ("gnumakefile", MAKE),
)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------


class ErroAnalise(Exception):
    """Erro que deve ser mostrado ao usuário (arquivo inexistente, binário etc.)."""


@dataclass
class Resultado:
    arquivo: str
    sistema: str
    linguagem: Linguagem
    origem: str                              # como a linguagem foi descoberta
    interpretador: Optional[str]             # caminho encontrado no sistema (None = não instalado)
    comandos: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    eh_pasta: bool = False                    # True quando o caminho é uma pasta de projeto


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------


def sistema_atual() -> str:
    """Devolve 'windows', 'linux' ou 'macos'."""
    nome = platform.system().lower()
    if nome.startswith("win"):
        return "windows"
    if nome == "darwin":
        return "macos"
    return "linux"  # Linux, BSDs e afins se comportam como Unix


def ler_texto(caminho: str, limite: int = 8192) -> str:
    """Lê o começo do arquivo como texto. Falha se o arquivo não existir ou for binário."""
    if not os.path.exists(caminho):
        raise ErroAnalise(f"Arquivo não encontrado: {caminho}")
    if os.path.isdir(caminho):
        raise ErroAnalise(f"O caminho é uma pasta, não um arquivo: {caminho}")
    try:
        with open(caminho, "rb") as f:
            bruto = f.read(limite)
    except PermissionError:
        raise ErroAnalise(f"Sem permissão para ler o arquivo: {caminho}")

    # Arquivos salvos em UTF-16 (comum em .ps1 do Windows) têm bytes nulos, mas são texto.
    if bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        return bruto.decode("utf-16", errors="replace")

    # Byte nulo ou cabeçalho de executável = binário (ELF do Linux, PE do Windows, Mach-O do macOS).
    magicos = (b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
    if b"\x00" in bruto or bruto.startswith(magicos):
        raise ErroAnalise(f"O arquivo é binário (programa compilado ou dados), não um script legível: {caminho}")

    if bruto.startswith(b"\xef\xbb\xbf"):  # BOM do UTF-8
        bruto = bruto[3:]
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("latin-1")  # nunca falha; scripts antigos costumam estar em latin-1


def ler_shebang(texto: str) -> Optional[Tuple[str, str]]:
    """Interpreta a primeira linha '#!...'.

    Devolve (linha_completa, nome_do_interpretador) ou None.
    Exemplos:
        #!/bin/bash                -> 'bash'
        #!/usr/bin/env node        -> 'node'
        #!/usr/bin/env -S deno run -> 'deno'
        #!/usr/bin/python3.11      -> 'python'
    """
    primeira = texto.splitlines()[0].strip() if texto else ""
    if not primeira.startswith("#!"):
        return None
    partes = primeira[2:].split()
    if not partes:
        return None
    programa = os.path.basename(partes[0])
    if programa == "env":
        # Pula as opções do env (-S, -i, VAR=valor) até chegar ao interpretador.
        resto = [p for p in partes[1:] if not p.startswith("-") and "=" not in p]
        if not resto:
            return None
        programa = os.path.basename(resto[0])
    # Tira o número de versão: python3.11 -> python, ruby2.7 -> ruby. Rscript fica como está.
    nome = programa.lower().rstrip("0123456789.")
    return primeira, nome or programa.lower()


def detectar(caminho: str, texto: str) -> Tuple[Linguagem, str]:
    """Descobre a linguagem: 1º pela extensão, 2º pelo shebang, 3º por pistas no conteúdo."""
    extensao = os.path.splitext(caminho)[1].lower()
    if extensao in POR_EXTENSAO:
        return POR_EXTENSAO[extensao], f"extensão {extensao}"

    shebang = ler_shebang(texto)
    if shebang:
        linha, nome = shebang
        if nome in POR_SHEBANG:
            return POR_SHEBANG[nome], f"shebang ({linha})"
        raise ErroAnalise(f"Shebang com interpretador desconhecido: {linha}")

    # Sem extensão e sem shebang: algumas pistas claras no início do arquivo.
    inicio = texto.lstrip().lower()
    if inicio.startswith("<?php"):
        return PHP, "conteúdo (<?php)"
    if inicio.startswith("@echo off"):
        return BATCH, "conteúdo (@echo off)"

    if extensao:
        raise ErroAnalise(f"Extensão {extensao} não reconhecida e o arquivo não tem shebang (#!) na primeira linha.")
    raise ErroAnalise("Não foi possível identificar a linguagem: o arquivo não tem extensão nem shebang (#!).")


# ---------------------------------------------------------------------------
# Montagem do comando
# ---------------------------------------------------------------------------


def citar(texto: str, sistema: str) -> str:
    """Coloca aspas no caminho quando necessário, do jeito que o terminal do sistema entende."""
    if sistema == "windows":
        return f'"{texto}"' if any(c in texto for c in ' &()^%!,;=') else texto
    return shlex.quote(texto)


def caminho_executavel(caminho: str) -> str:
    """No Unix, './script' é obrigatório para rodar um arquivo da pasta atual."""
    if os.path.isabs(caminho) or caminho.startswith(("./", "../")):
        return caminho
    return "./" + caminho


def analisar_pasta(caminho: str, sistema: str,
                   which: Callable[[str], Optional[str]]) -> Resultado:
    """Quando o caminho é uma pasta, descobre o tipo de projeto e os comandos para prepará-lo."""
    arquivos = {nome.lower() for nome in os.listdir(caminho)}
    for marcador, projeto in MARCADORES_PROJETO:
        if marcador in arquivos:
            break
    else:
        raise ErroAnalise(
            "É uma pasta, mas não reconheci o tipo de projeto (não achei configure, Makefile, "
            "package.json, requirements.txt, Cargo.toml e afins). Abra a pasta e arraste um "
            "arquivo de script específico.")

    # Reaproveita o Resultado usando um 'Linguagem' sintético só para nome e requisito.
    falso = Linguagem(projeto.nome, projeto.requisito)
    resultado = Resultado(caminho, sistema, falso, f"pasta de projeto ({marcador})",
                          interpretador=None, eh_pasta=True)
    if projeto.ferramenta:
        local = which(projeto.ferramenta)
        resultado.interpretador = local
        if not local:
            dica = f" Baixe em: {projeto.instalar}" if projeto.instalar else ""
            resultado.avisos.append(f"{projeto.requisito}: '{projeto.ferramenta}' não foi encontrado "
                                    f"neste computador.{dica}")
    resultado.comandos.append(f"cd {citar(caminho, sistema)}")
    resultado.comandos.extend(projeto.passos)
    if projeto.observacao:
        resultado.avisos.append(projeto.observacao)
    return resultado


def analisar(caminho: str, sistema: Optional[str] = None,
             which: Callable[[str], Optional[str]] = shutil.which) -> Resultado:
    """Analisa o script (ou pasta de projeto) e monta as instruções de execução."""
    sistema = sistema or sistema_atual()
    if os.path.isdir(caminho):
        return analisar_pasta(caminho, sistema, which)
    texto = ler_texto(caminho)
    linguagem, origem = detectar(caminho, texto)
    resultado = Resultado(caminho, sistema, linguagem, origem, interpretador=None)
    windows = sistema == "windows"

    if linguagem.apenas and linguagem.apenas != sistema:
        resultado.avisos.append(
            f"{linguagem.nome} só roda no {NOMES_SISTEMA[linguagem.apenas]}; "
            f"não há como executá-lo diretamente no {NOMES_SISTEMA[sistema]}.")
        return resultado

    candidatos = linguagem.windows if windows else linguagem.unix
    if not candidatos:
        resultado.avisos.append(f"Não há interpretador conhecido de {linguagem.nome} para {NOMES_SISTEMA[sistema]}.")
        return resultado

    # Usa o primeiro interpretador da lista que estiver instalado.
    escolhido = candidatos[0]
    for nome in candidatos:
        local = which(nome)
        if local:
            escolhido, resultado.interpretador = nome, local
            break
    if not resultado.interpretador:
        dica = f" Baixe em: {linguagem.instalar}" if linguagem.instalar else ""
        resultado.avisos.append(f"{linguagem.requisito} não foi encontrado neste computador.{dica}")

    if escolhido == "deno":  # TypeScript pelo Deno usa 'deno run' em vez de 'npx tsx'
        argumentos: Tuple[str, ...] = ("run",)
    else:
        argumentos = linguagem.args_windows if windows else linguagem.args_unix

    if linguagem.shell_unix and not windows:
        # Scripts de shell no Unix: dar permissão de execução e rodar direto (o shebang escolhe o shell).
        if not ler_shebang(texto):
            resultado.avisos.append(
                "O script não tem shebang (#!) na primeira linha; recomenda-se adicionar "
                f"'#!/usr/bin/env {escolhido}' para garantir o shell correto.")
        if not os.access(caminho, os.X_OK):
            resultado.comandos.append(f"chmod +x {citar(caminho, sistema)}")
        resultado.comandos.append(citar(caminho_executavel(caminho), sistema))
    else:
        partes = [escolhido, *argumentos, citar(caminho, sistema)]
        resultado.comandos.append(" ".join(partes))
        if windows and linguagem in (SHELL, SH):
            resultado.avisos.append("No Windows, scripts de shell rodam pelo Git Bash ou pelo WSL.")

    return resultado


# ---------------------------------------------------------------------------
# Saída no terminal
# ---------------------------------------------------------------------------


def formatar(resultado: Resultado) -> str:
    rotulo_alvo = "Pasta" if resultado.eh_pasta else "Arquivo"
    rotulo_tipo = "Projeto" if resultado.eh_pasta else "Linguagem"
    linhas = [
        "=" * 60,
        f" {(rotulo_alvo + ':').ljust(13)} {resultado.arquivo}",
        f" {'Sistema:'.ljust(13)} {NOMES_SISTEMA[resultado.sistema]}",
        f" {(rotulo_tipo + ':').ljust(13)} {resultado.linguagem.nome}  (por {resultado.origem})",
        f" Requisito:    {resultado.linguagem.requisito}",
    ]
    if resultado.interpretador:
        linhas.append(f" Instalado em: {resultado.interpretador}")
    elif resultado.comandos:
        linhas.append(" Instalado em: NÃO ENCONTRADO")
    if resultado.comandos:
        titulo = " Copie e cole no terminal (um comando por vez):" if resultado.eh_pasta \
            else " Copie e cole no terminal:"
        linhas += ["-" * 60, titulo, ""]
        linhas += [f"   {c}" for c in resultado.comandos]
    for aviso in resultado.avisos:
        linhas.append(f"\n ⚠ {aviso}")
    linhas.append("=" * 60)
    return "\n".join(linhas)


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Consoles antigos do Windows (cp1252) não têm alguns símbolos; troca em vez de travar.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(errors="replace")
    if not argv:
        try:
            caminho = input("Caminho do script: ").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            return 1
        argv = [caminho] if caminho else []
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1

    codigo = 0
    for caminho in argv:
        try:
            print(formatar(analisar(caminho)))
        except ErroAnalise as erro:
            print(f"Erro: {erro}", file=sys.stderr)
            codigo = 1
    return codigo


if __name__ == "__main__":
    sys.exit(main())
