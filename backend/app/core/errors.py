"""API error type and handlers. All errors share the shape {"error": {"code", "message"}}."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", []) if p not in ("body", "query"))
            parts.append(f"{loc}: {e.get('msg', 'invalid value')}" if loc else e.get("msg", "invalid"))
        return JSONResponse(status_code=422, content=_body("invalid_parameters", "; ".join(parts)))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        # Never leak internals or file paths.
        return JSONResponse(status_code=500, content=_body("internal_error", "Unexpected server error."))
