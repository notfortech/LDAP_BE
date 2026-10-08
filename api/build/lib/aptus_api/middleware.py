"""Response hardening.

Browser-facing basics. Cheap to add and among the first things an
institutional IT reviewer checks.
"""

from starlette.middleware.base import BaseHTTPMiddleware

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The API serves JSON only; nothing should ever be executed or framed
    # from it, so the policy can be maximally restrictive.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, production: bool):
        super().__init__(app)
        self._headers = dict(_HEADERS)
        if production:
            self._headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        return response
