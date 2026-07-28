"""Avvia l'interfaccia web sulla rete locale."""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "sudoku_app.web.app:create_app",
        factory=True,
        host=os.environ.get("SUDOKU_WEB_HOST", "0.0.0.0"),
        port=int(os.environ.get("SUDOKU_WEB_PORT", "8000")),
    )
