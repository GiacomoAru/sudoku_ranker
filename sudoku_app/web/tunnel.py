"""Gestione del processo Cloudflare Quick Tunnel."""

import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import Event, Thread


PUBLIC_URL_PATTERN = re.compile(
    r"https://[a-z0-9-]+\.trycloudflare\.com",
    re.IGNORECASE,
)


class QuickTunnelError(RuntimeError):
    """Il tunnel pubblico non può essere avviato."""


class QuickTunnel:
    """Avvia cloudflared e pubblica l'URL in file di stato locali."""

    def __init__(
        self,
        origin_url,
        state_directory,
        executable=None,
    ):
        self.origin_url = origin_url
        self.state_directory = Path(state_directory)
        self.executable = executable
        self.process = None
        self.public_url = None
        self._reader = None
        self._url_ready = Event()
        self._log_lines = []
        self.pid_path = self.state_directory / ".sudoku-web-tunnel.pid"
        self.url_path = self.state_directory / ".sudoku-web-public-url"
        self.log_path = self.state_directory / ".sudoku-web-tunnel.log"

    def _resolve_executable(self):
        configured = self.executable or os.environ.get(
            "SUDOKU_CLOUDFLARED_PATH",
        )
        if configured:
            path = Path(configured).expanduser()
            if path.is_file():
                return str(path.resolve())
            raise QuickTunnelError(
                f"cloudflared non trovato nel percorso configurato: {path}"
            )

        discovered = shutil.which("cloudflared")
        if discovered:
            return discovered

        local_names = (
            "cloudflared.exe",
            "cloudflared",
        )
        for name in local_names:
            candidate = self.state_directory / "tools" / name
            if candidate.is_file():
                return str(candidate.resolve())

        raise QuickTunnelError(
            "cloudflared non è installato. Consulta WEB_LAN.md, sezione "
            "'Accesso da Internet'."
        )

    def start(self, timeout=25):
        executable = self._resolve_executable()
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self._remove_state_files()

        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

        self.process = subprocess.Popen(
            [
                executable,
                "tunnel",
                "--no-autoupdate",
                "--url",
                self.origin_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
        self.pid_path.write_text(
            str(self.process.pid),
            encoding="ascii",
        )
        self._reader = Thread(
            target=self._read_output,
            name="cloudflared-output",
            daemon=True,
        )
        self._reader.start()

        if not self._url_ready.wait(timeout):
            return_code = self.process.poll()
            details = "\n".join(self._log_lines[-8:])
            self.stop()
            if return_code is None:
                reason = (
                    f"nessun URL ricevuto entro {timeout} secondi"
                )
            else:
                reason = f"cloudflared terminato con codice {return_code}"
            if details:
                reason = f"{reason}\n{details}"
            raise QuickTunnelError(
                f"Impossibile aprire il tunnel: {reason}"
            )

        return self.public_url

    def _read_output(self):
        with self.log_path.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as log_file:
            for raw_line in self.process.stdout:
                line = raw_line.rstrip()
                self._log_lines.append(line)
                log_file.write(f"{line}\n")
                log_file.flush()

                match = PUBLIC_URL_PATTERN.search(line)
                if match and self.public_url is None:
                    self.public_url = match.group(0)
                    self.url_path.write_text(
                        self.public_url,
                        encoding="ascii",
                    )
                    self._url_ready.set()

    def stop(self):
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        self.process = None
        self.pid_path.unlink(missing_ok=True)
        self.url_path.unlink(missing_ok=True)

    def _remove_state_files(self):
        self.pid_path.unlink(missing_ok=True)
        self.url_path.unlink(missing_ok=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _error_type, _error, _traceback):
        self.stop()
