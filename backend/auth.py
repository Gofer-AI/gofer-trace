"""
auth.py — API-key authentication and principal resolution.

Local profile (`GOFER_REQUIRE_AUTH=false`, the default) is single-user: every request
resolves to the principal "local" and nothing is scoped — behavior is unchanged. Cloud
profile enforces a key from `GOFER_API_KEYS` and resolves it to a principal used to scope
workflows per user.

Keys are read via the `Authorization: Bearer <key>` or `X-API-Key` header.
"""
from __future__ import annotations

LOCAL_PRINCIPAL = "local"


class AuthError(Exception):
    """Raised when auth is required and the API key is missing/invalid. main.py maps
    this to an HTTP 401 (keeps this module free of a FastAPI import)."""

    def __init__(self, detail: str = "Missing or invalid API key.", status_code: int = 401):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _extract_key(authorization: str, x_api_key: str) -> str:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    return ""


def resolve_principal(settings, authorization: str = "", x_api_key: str = "") -> str:
    """Return the caller's principal, or raise 401 when auth is required and the key is bad."""
    if not settings.require_auth:
        return LOCAL_PRINCIPAL

    key = _extract_key(authorization, x_api_key)
    principal = settings.api_keys.get(key)
    if not principal:
        raise AuthError("Missing or invalid API key.")
    return principal


def owner_for(settings, principal: str) -> str | None:
    """The owner to scope by: the principal in cloud, None (no scoping) in local."""
    return principal if settings.require_auth else None
