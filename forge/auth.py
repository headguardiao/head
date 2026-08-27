from __future__ import annotations

import hmac
import logging

from aiohttp import web

logger = logging.getLogger(__name__)

# Public by design: /health and /signal/* are unauthenticated public
# market data (no user_id, no secrets - see README "Segurança"). /dashboard
# and / serve the static test UI itself, which contains no secrets; the
# *data* it fetches goes through the same protected endpoints as any
# other caller. Deliberately NOT injecting the API key into the served
# HTML - that would leak the secret to anyone who merely loads the page.
_PUBLIC_PATHS = {"/health", "/dashboard", "/"}
_PUBLIC_PREFIXES = ("/signal/",)


def _is_public(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)


def build_auth_middleware(api_key: str | None):
    """Bearer-token auth for server-to-server callers (e.g. the main
    app's own backend). api_key=None disables enforcement entirely -
    matches this repo's existing behavior for local-only use, but every
    endpoint is then reachable by anyone who can reach the port at all.
    Set FORGE_API_KEY before exposing this beyond localhost/a trusted
    network."""

    if api_key is None:
        logger.warning(
            "FORGE_API_KEY not set - all endpoints are UNAUTHENTICATED. "
            "Fine for local-only use; set FORGE_API_KEY before this is reachable "
            "from anywhere else."
        )

    @web.middleware
    async def middleware(request: web.Request, handler):
        if api_key is None or _is_public(request.path):
            return await handler(request)

        header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        provided = header[len(prefix) :] if header.startswith(prefix) else ""
        if not provided or not hmac.compare_digest(provided, api_key):
            return web.json_response({"error": "missing or invalid Authorization header"}, status=401)
        return await handler(request)

    return middleware
