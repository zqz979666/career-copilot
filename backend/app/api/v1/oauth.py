"""OAuth endpoints — 3rd-party account linking (v0.8).

Endpoints:

    GET  /api/v1/oauth/github/authorize   → build authorize URL + issue state cookie
    GET  /api/v1/oauth/github/callback    → exchange code, upsert connection
    GET  /api/v1/oauth                    → list this user's connections
    DELETE /api/v1/oauth/{provider}       → unlink

The ``state`` CSRF token is stored server-side in a short-lived cookie that we
require to be echoed back on ``callback``. This is the same pattern the tech
guide § 6.3 mandates for the GitHub adapter.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.dependencies import (
    get_current_user_id,
    get_github_sync_service,
    get_oauth_service,
)
from app.integrations.github import GitHubClient
from app.logging_config import get_logger
from app.models.schemas import (
    GitHubSyncResponse,
    OAuthAuthorizeResponse,
    OAuthCallbackResponse,
    OAuthConnectionOut,
    OAuthConnectionsList,
)
from app.services.github_sync_service import GitHubSyncError, GitHubSyncService
from app.services.oauth_service import OAuthError, OAuthService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/oauth", tags=["oauth"])

# Cookie names — short-lived, HttpOnly. ``uid`` binds the state to the account
# that started the flow so the callback can't be replayed against a different
# session.
_STATE_COOKIE = "oauth_state"
_UID_COOKIE = "oauth_uid"
_COOKIE_MAX_AGE_SECONDS = 600


def _cookie_kwargs() -> dict:
    settings = get_settings()
    return {
        "max_age": _COOKIE_MAX_AGE_SECONDS,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.is_production,
        "path": "/api/v1/oauth",
    }


@router.get("/github/authorize", response_model=OAuthAuthorizeResponse)
async def github_authorize(
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthAuthorizeResponse:
    state = GitHubClient.generate_state()
    try:
        url = oauth.github_build_authorize_url(state)
    except OAuthError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e

    response.set_cookie(_STATE_COOKIE, state, **_cookie_kwargs())
    response.set_cookie(_UID_COOKIE, str(user_id), **_cookie_kwargs())
    return OAuthAuthorizeResponse(provider="github", authorize_url=url, state=state)


@router.get("/calendar/authorize", response_model=OAuthAuthorizeResponse)
async def calendar_authorize(
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthAuthorizeResponse:
    state = GitHubClient.generate_state()
    response.set_cookie(_STATE_COOKIE, state, **_cookie_kwargs())
    response.set_cookie(_UID_COOKIE, str(user_id), **_cookie_kwargs())
    return OAuthAuthorizeResponse(
        provider="calendar",
        authorize_url=oauth.calendar_build_authorize_url(state),
        state=state,
    )


@router.get("/jira/authorize", response_model=OAuthAuthorizeResponse)
async def jira_authorize(
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthAuthorizeResponse:
    state = GitHubClient.generate_state()
    response.set_cookie(_STATE_COOKIE, state, **_cookie_kwargs())
    response.set_cookie(_UID_COOKIE, str(user_id), **_cookie_kwargs())
    return OAuthAuthorizeResponse(
        provider="jira",
        authorize_url=oauth.jira_build_authorize_url(state),
        state=state,
    )


@router.get("/github/callback")
async def github_callback(
    request: Request,
    response: Response,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthCallbackResponse:
    """Exchange the code and persist the encrypted OAuth connection."""
    stored_state = request.cookies.get(_STATE_COOKIE) or ""
    stored_uid = request.cookies.get(_UID_COOKIE) or ""
    # NOTE: constant-time compare not necessary here — the state is a random
    # 24-byte token, the header just guards against CSRF, not timing attacks.
    if not stored_state or stored_state != state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_state_mismatch")
    if not stored_uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_uid_missing")

    try:
        user_id = UUID(stored_uid)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_uid_invalid") from e

    try:
        conn = await oauth.github_complete(user_id, code)
    except OAuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    # Rotate cookies so a stolen state can't be replayed.
    response.delete_cookie(_STATE_COOKIE, path="/api/v1/oauth")
    response.delete_cookie(_UID_COOKIE, path="/api/v1/oauth")

    return OAuthCallbackResponse(
        connection=OAuthConnectionOut(**oauth.to_dict(conn)),
        should_sync=True,
    )


@router.get("/calendar/callback", response_model=OAuthCallbackResponse)
async def calendar_callback(
    request: Request,
    response: Response,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthCallbackResponse:
    stored_state = request.cookies.get(_STATE_COOKIE) or ""
    stored_uid = request.cookies.get(_UID_COOKIE) or ""
    if not stored_state or stored_state != state or not stored_uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_state_mismatch")
    try:
        user_id = UUID(stored_uid)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_uid_invalid") from e
    conn = await oauth.generic_complete(user_id=user_id, provider="calendar", code=code)
    response.delete_cookie(_STATE_COOKIE, path="/api/v1/oauth")
    response.delete_cookie(_UID_COOKIE, path="/api/v1/oauth")
    return OAuthCallbackResponse(connection=OAuthConnectionOut(**oauth.to_dict(conn)), should_sync=True)


@router.get("/jira/callback", response_model=OAuthCallbackResponse)
async def jira_callback(
    request: Request,
    response: Response,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthCallbackResponse:
    stored_state = request.cookies.get(_STATE_COOKIE) or ""
    stored_uid = request.cookies.get(_UID_COOKIE) or ""
    if not stored_state or stored_state != state or not stored_uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_state_mismatch")
    try:
        user_id = UUID(stored_uid)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth_uid_invalid") from e
    conn = await oauth.generic_complete(user_id=user_id, provider="jira", code=code)
    response.delete_cookie(_STATE_COOKIE, path="/api/v1/oauth")
    response.delete_cookie(_UID_COOKIE, path="/api/v1/oauth")
    return OAuthCallbackResponse(connection=OAuthConnectionOut(**oauth.to_dict(conn)), should_sync=True)


@router.get("/github/callback/redirect")
async def github_callback_redirect(
    request: Request,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    oauth: OAuthService = Depends(get_oauth_service),
) -> RedirectResponse:
    """Same as :func:`github_callback` but redirects into the SPA.

    Some UX flows want to bounce the user back to a specific page (e.g. the
    Profile / Integrations tab). Frontends can opt in by pointing GitHub at
    this URL instead of ``/callback``.
    """
    stored_state = request.cookies.get(_STATE_COOKIE) or ""
    stored_uid = request.cookies.get(_UID_COOKIE) or ""
    settings = get_settings()
    redirect_target = (settings.cors_origin_list[0] if settings.cors_origin_list else "/") + "/integrations"

    if not stored_state or stored_state != state or not stored_uid:
        return RedirectResponse(url=f"{redirect_target}?oauth=error", status_code=302)
    try:
        user_id = UUID(stored_uid)
    except ValueError:
        return RedirectResponse(url=f"{redirect_target}?oauth=error", status_code=302)
    try:
        await oauth.github_complete(user_id, code)
    except OAuthError:
        return RedirectResponse(url=f"{redirect_target}?oauth=error", status_code=302)
    resp = RedirectResponse(url=f"{redirect_target}?oauth=ok", status_code=302)
    resp.delete_cookie(_STATE_COOKIE, path="/api/v1/oauth")
    resp.delete_cookie(_UID_COOKIE, path="/api/v1/oauth")
    return resp


@router.get("", response_model=OAuthConnectionsList)
async def list_connections(
    user_id: UUID = Depends(get_current_user_id),
    oauth: OAuthService = Depends(get_oauth_service),
) -> OAuthConnectionsList:
    conns = await oauth.list_connections(user_id)
    return OAuthConnectionsList(
        items=[OAuthConnectionOut(**oauth.to_dict(c)) for c in conns]
    )


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    provider: str,
    user_id: UUID = Depends(get_current_user_id),
    oauth: OAuthService = Depends(get_oauth_service),
) -> Response:
    if provider not in {"github", "calendar", "jira"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported_provider")
    deleted = await oauth.disconnect(user_id, provider)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connection_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Manual sync trigger ----------


@router.post("/github/sync", response_model=GitHubSyncResponse)
async def github_manual_sync(
    user_id: UUID = Depends(get_current_user_id),
    svc: GitHubSyncService = Depends(get_github_sync_service),
) -> GitHubSyncResponse:
    """Pull the user's recent PRs and fold them into their Profile.

    Manual button on the Integrations page — used when the user just linked
    or when webhooks are misconfigured (e.g. private-repo hooks the user
    hasn't installed yet).
    """
    settings = get_settings()
    try:
        result = await svc.sync_pull_requests(user_id, limit=settings.github_sync_max_prs)
    except GitHubSyncError as e:
        # 400 gives the client actionable info; 503 would suggest transient.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return GitHubSyncResponse(
        fetched=result.fetched,
        created=result.created,
        updated=result.updated,
        skipped_duplicates=result.skipped_duplicates,
    )
