"""
Clipp Engine — Railway Auth Middleware
======================================
On Railway, the engine's private networking is already
isolated within the project. This middleware adds a
defense-in-depth secret header check without needing Nginx.

Place this file in the root of MoneyPrinterTurbo and
import it in main.py before the app starts.

Usage in main.py:
    from clipp_auth import ClippAuthMiddleware
    app.add_middleware(ClippAuthMiddleware)
"""

import os
import hmac
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


INTERNAL_SECRET = os.environ.get("INTERNAL_API_SECRET", "")
EXEMPT_PATHS    = {"/api/v1/health", "/health", "/"}


class ClippAuthMiddleware(BaseHTTPMiddleware):
    """
    Validates the X-Clipp-Internal-Secret header on every request.
    Exempt paths (health checks) bypass the check.
    """

    async def dispatch(self, request: Request, call_next):
        # Allow health checks without auth
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # Validate secret header
        provided = request.headers.get("x-clipp-internal-secret", "")

        if not INTERNAL_SECRET:
            # Fail closed — if secret not configured, block everything
            return JSONResponse(
                {"error": "Engine not configured: INTERNAL_API_SECRET missing"},
                status_code=503
            )

        # Constant-time comparison prevents timing attacks
        if not hmac.compare_digest(provided.encode(), INTERNAL_SECRET.encode()):
            return JSONResponse(
                {"error": "Forbidden"},
                status_code=403
            )

        return await call_next(request)
