"""Abre o Atlas: python -m atlas [--porta 8765] [--sem-navegador]"""

import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

from .config import pasta_dados


def _abrir_quando_pronto(endereco: str, porta: int) -> None:
    """Espera o servidor aceitar conexões antes de abrir o navegador."""
    fim = time.monotonic() + 60
    while time.monotonic() < fim:
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.5).close()
        except OSError:
            time.sleep(0.2)
            continue
        webbrowser.open(endereco)
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas — IA pessoal do Erton")
    parser.add_argument("--porta", type=int, default=8765)
    parser.add_argument("--sem-navegador", action="store_true")
    args = parser.parse_args()

    endereco = f"http://127.0.0.1:{args.porta}"
    if not args.sem_navegador:
        threading.Thread(target=_abrir_quando_pronto, args=(endereco, args.porta), daemon=True).start()
    print(f"Atlas no ar em {endereco}  (feche esta janela para desligar)")
    print(f"Chave e memória ficam em: {pasta_dados()}")
    uvicorn.run("atlas.servidor:app", host="127.0.0.1", port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()
