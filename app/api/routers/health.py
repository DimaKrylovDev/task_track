from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import HealthResponse
from app.core.exceptions import AppError
from app.db.session import session_factory

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return HealthResponse(status="ok", database="ok")
    except SQLAlchemyError as exc:
        error = AppError("Database is unavailable")
        error.status_code = 503
        error.code = "service_unavailable"
        raise error from exc

