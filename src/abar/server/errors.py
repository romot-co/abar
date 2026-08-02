"""HTTP error envelope construction."""

from fastapi.responses import JSONResponse

from abar.app.views import ErrorEnvelope, ErrorView


def error_response(status: int, code: str, message: str) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorView(code=code, message=message))
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"))
