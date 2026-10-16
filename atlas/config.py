"""Configuração do Atlas: pasta de dados e chave da Anthropic.

Tudo fica em <pasta do usuário>\\Documents\\Atlas (a pasta local, fora do OneDrive).
O caminho exato aparece na janela preta ao iniciar e em ⚙ Configurar.
A pasta pode ser trocada com a variável de ambiente ATLAS_PASTA.
"""

import os
from pathlib import Path

MODELO = os.environ.get("ATLAS_MODELO", "claude-opus-5-5")
ESFORCO = os.environ.get("ATLAS_ESFORCO", "high")


def pasta_dados() -> Path:
    pasta = os.environ.get("ATLAS_PASTA")
    # Caminho fixo: não depende de qual pasta existe hoje, para não mudar de lugar depois.
    caminho = Path(pasta) if pasta else Path.home() / "Documents" / "Atlas"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _arquivo_config() -> Path:
    return pasta_dados() / "config.env"


def ler_chave() -> str | None:
    """Chave salva em ⚙ Configurar; se não houver, a da variável ANTHROPIC_API_KEY."""
    arquivo = _arquivo_config()
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
            if linha.startswith("ANTHROPIC_API_KEY="):
                valor = linha.split("=", 1)[1].strip()
                if valor:
                    return valor
    chave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return chave or None


def salvar_chave(chave: str) -> None:
    chave = chave.strip()
    if not chave.startswith("sk-ant-"):
        raise ValueError("A chave da Anthropic começa com sk-ant-")
    _arquivo_config().write_text(f"ANTHROPIC_API_KEY={chave}\n", encoding="utf-8")
