from fastapi import FastAPI
from pydantic import BaseModel

SERVICE_NAME = "gateway"

app = FastAPI(title=SERVICE_NAME)


class HealthResponse(BaseModel):
    status: str
    service: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)
