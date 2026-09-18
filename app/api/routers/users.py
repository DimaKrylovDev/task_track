from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, ReadUowDep
from app.api.schemas import UserPut, UserRead
from app.services.users import UserService

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.put("/me", response_model=UserRead)
async def update_me(body: UserPut, current_user: CurrentUser, uow: ReadUowDep) -> UserRead:
    user = await UserService(uow).update(current_user.id, body.email, body.display_name)
    return UserRead.model_validate(user)


@router.get("", response_model=list[UserRead])
async def search_users(
    q: Annotated[str, Query(min_length=2, max_length=120)],
    current_user: CurrentUser,
    uow: ReadUowDep,
) -> list[UserRead]:
    users = await UserService(uow).search(q)
    return [UserRead.model_validate(user) for user in users]

