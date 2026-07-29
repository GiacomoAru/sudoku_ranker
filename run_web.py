"""Avvia l'interfaccia web in locale, LAN oppure su Internet."""

import os
from pathlib import Path

import uvicorn

from sudoku_app.web.app import create_app
from sudoku_app.web.tunnel import QuickTunnel, QuickTunnelError


# Variabile principale: "local", "lan" oppure "internet".
# Può essere modificata qui oppure sovrascritta con SUDOKU_WEB_EXPOSURE.
EXPOSURE_MODE = "internet"

PROJECT_ROOT = Path(__file__).resolve().parent
VALID_EXPOSURE_MODES = {"local", "lan", "internet"}


def _configuration():
    mode = os.environ.get(
        "SUDOKU_WEB_EXPOSURE",
        EXPOSURE_MODE,
    ).strip().casefold()
    if mode not in VALID_EXPOSURE_MODES:
        raise ValueError(
            "Modalità non valida: usa local, lan oppure internet."
        )

    port = int(os.environ.get("SUDOKU_WEB_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("SUDOKU_WEB_PORT deve essere tra 1 e 65535.")

    default_host = {
        "local": "127.0.0.1",
        "lan": "0.0.0.0",
        "internet": "127.0.0.1",
    }[mode]
    host = os.environ.get("SUDOKU_WEB_HOST", default_host)
    if mode == "internet" and host not in {"127.0.0.1", "localhost"}:
        raise ValueError(
            "In modalità internet il server deve restare su 127.0.0.1; "
            "il tunnel gestisce l'accesso pubblico."
        )

    username = os.environ.get(
        "SUDOKU_WEB_ACCESS_USERNAME",
        "sudoku",
    )
    password = os.environ.get("SUDOKU_WEB_ACCESS_PASSWORD")
    if mode == "internet":
        if not password or len(password) < 12:
            raise ValueError(
                "Imposta SUDOKU_WEB_ACCESS_PASSWORD con almeno 12 "
                "caratteri prima di usare la modalità internet."
            )
        if ":" in username:
            raise ValueError(
                "SUDOKU_WEB_ACCESS_USERNAME non può contenere ':'."
            )

    return mode, host, port, username, password


def main():
    mode, host, port, username, password = _configuration()
    tunnel = None

    if mode == "internet":
        tunnel = QuickTunnel(
            origin_url=f"http://127.0.0.1:{port}",
            state_directory=PROJECT_ROOT,
        )
        print("Apertura del tunnel HTTPS pubblico...")
        public_url = tunnel.start()
        print("")
        print(f"URL PUBBLICO: {public_url}")
        print(f"Utente: {username}")
        print("Apri questo URL dal telefono, anche fuori dalla Wi-Fi.")
        print("")
    elif mode == "lan":
        print(f"Server LAN sulla porta {port}.")
    else:
        print(f"Server locale: http://127.0.0.1:{port}")

    try:
        app = create_app(
            exposure_mode=mode,
            access_username=username,
            access_password=password,
        )
        server_options = {
            "host": host,
            "port": port,
        }
        if mode == "internet":
            server_options.update({
                "proxy_headers": True,
                "forwarded_allow_ips": "127.0.0.1",
            })
        uvicorn.run(app, **server_options)
    finally:
        if tunnel is not None:
            tunnel.stop()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, QuickTunnelError) as error:
        raise SystemExit(f"ERRORE: {error}") from error
