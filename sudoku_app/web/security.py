"""Controlli di accesso e header di sicurezza per l'interfaccia web."""

import base64
import binascii
import secrets

from fastapi import Request
from fastapi.responses import Response


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Sudoku-Logic-Lab": "1",
}


def _credentials_from_header(value):
    if not value:
        return None

    scheme, separator, encoded = value.partition(" ")
    if not separator or scheme.casefold() != "basic":
        return None

    try:
        decoded = base64.b64decode(
            encoded.strip(),
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None

    username, separator, password = decoded.partition(":")
    if not separator:
        return None

    return username, password


def _authorised(request, username, password):
    credentials = _credentials_from_header(
        request.headers.get("authorization"),
    )
    if credentials is None:
        return False

    supplied_username, supplied_password = credentials
    return (
        secrets.compare_digest(
            supplied_username.encode("utf-8"),
            username.encode("utf-8"),
        )
        and secrets.compare_digest(
            supplied_password.encode("utf-8"),
            password.encode("utf-8"),
        )
    )


def install_security_middleware(app, username=None, password=None):
    """Protegge tutte le route quando è configurata una password."""
    authentication_enabled = bool(password)

    @app.middleware("http")
    async def secure_request(request: Request, call_next):
        if authentication_enabled and not _authorised(
            request,
            username,
            password,
        ):
            response = Response(
                content="Autenticazione richiesta.",
                status_code=401,
                media_type="text/plain",
                headers={
                    "WWW-Authenticate": (
                        'Basic realm="Sudoku Logic Lab", charset="UTF-8"'
                    ),
                },
            )
        else:
            response = await call_next(request)

        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        if request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000",
            )

        return response

    return authentication_enabled
