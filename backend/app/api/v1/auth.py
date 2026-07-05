"""Auth endpoints (register / login / me)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_auth_service, get_current_user_id
from app.models.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        user = await auth.register(email=body.email, password=body.password, name=body.name)
    except AuthError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    token, expires_in = auth.issue_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        user = await auth.authenticate(email=body.email, password=body.password)
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e
    token, expires_in = auth.issue_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
async def me(
    current_user_id: UUID = Depends(get_current_user_id),
    auth: AuthService = Depends(get_auth_service),
) -> UserOut:
    user = await auth._users.get_by_id(current_user_id)  # type: ignore[attr-defined]
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    return UserOut.model_validate(user)
