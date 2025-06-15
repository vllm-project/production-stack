import httpx
from fastapi import Request # fastapi.Request is starlette.requests.Request
from fastapi.responses import JSONResponse # fastapi.responses.JSONResponse inherits from starlette.responses.Response
from http import HTTPStatus
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse # For type hinting call_next
from typing import Callable, Awaitable


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_token_server_url: str | None):
        super().__init__(app)
        self.auth_token_server_url = auth_token_server_url

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]):
        if not self.auth_token_server_url:
            response = await call_next(request)
            return response

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=HTTPStatus.UNAUTHORIZED,
                content={"detail": "Not authenticated"},
            )

        token = auth_header.split(" ")[1]

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self.auth_token_server_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == HTTPStatus.OK:
                    response = await call_next(request)
                    return response
                else:
                    return JSONResponse(
                        status_code=HTTPStatus.UNAUTHORIZED,
                        content={"detail": "Invalid token"},
                    )
            except httpx.RequestError as e:
                # Log the error e
                return JSONResponse(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    content={"detail": "Error contacting authentication server"},
                )
