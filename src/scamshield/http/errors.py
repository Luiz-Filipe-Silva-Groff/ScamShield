from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, retry: int | None = None):
        self.status, self.code, self.message, self.retry = status, code, message, retry
        super().__init__(code)


async def api_error(request: Request, exc: APIError):
    headers = {"Retry-After": str(exc.retry)} if exc.retry is not None else {}
    return JSONResponse(
        status_code=exc.status,
        headers=headers,
        content={
            "error": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", str(uuid4())),
        },
    )


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                    ]
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)
