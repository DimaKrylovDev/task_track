from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.routers import auth, comments, health, projects, tags, tasks, users
from app.core.config import settings
from app.core.exceptions import AppError

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Командный трекер задач с многослойной архитектурой.",
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "conflict",
                "message": "The operation conflicts with existing data",
                "details": None,
            }
        },
    )


for api_router in (health.router, auth.router, users.router, projects.router, tasks.router,
                   tags.router, comments.router):
    app.include_router(api_router)
