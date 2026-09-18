from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, UowDep
from app.api.schemas import AuthResponse, LoginRequest, RefreshRequest, RegisterRequest, TokenPair
from app.services.auth import AuthService

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, uow: UowDep) -> AuthResponse:
    user, tokens = await AuthService(uow).register(body.email, body.display_name, body.password)
    return AuthResponse(user=user, tokens=TokenPair.model_validate(tokens))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, uow: UowDep) -> AuthResponse:
    user, tokens = await AuthService(uow).login(body.email, body.password)
    return AuthResponse(user=user, tokens=TokenPair.model_validate(tokens))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, uow: UowDep) -> TokenPair:
    tokens = await AuthService(uow).refresh(body.refresh_token)
    return TokenPair.model_validate(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, uow: UowDep, current_user: CurrentUser) -> Response:
    await AuthService(uow).logout(body.refresh_token, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
