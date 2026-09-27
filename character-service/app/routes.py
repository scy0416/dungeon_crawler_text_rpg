from fastapi import APIRouter

from app.schemas import HealthResponse

SERVICE_NAME = "character-service"

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)
