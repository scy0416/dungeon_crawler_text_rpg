from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class VerifyResponse(BaseModel):
    """auth-service `GET /auth/verify` 응답."""

    user_id: int
    username: str
