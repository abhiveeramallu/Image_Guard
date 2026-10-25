from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
