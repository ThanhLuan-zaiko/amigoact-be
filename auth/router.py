"""HTTP layer for auth: parsing, status codes, cookies. No business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, Response

from auth.schemas import (
    AcceptedResponse,
    ChangePasswordRequest,
    DevChallengeRequest,
    DevChallengeResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserProfile,
    VerifyEmailRequest,
)
from auth.service import SessionProfile, TokenPair
from core.config import Settings, get_settings
from core.dependencies import CurrentUser, get_auth_service, get_current_user
from core.exceptions import NotFoundError, UnauthorizedError
from core.security import hash_token

if TYPE_CHECKING:
    from auth.service import AuthService

REFRESH_COOKIE = "amigoact_refresh"

router = APIRouter(tags=["auth"])


def _profile_schema(profile: SessionProfile) -> UserProfile:
    return UserProfile(
        id=profile.id,
        email=profile.email,
        phone=profile.phone,
        full_name=profile.full_name,
        email_verified=profile.email_verified,
        created_at=profile.created_at,
    )


def _token_schema(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        expires_in=pair.expires_in,
    )


def _write_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        path="/",
        httponly=True,
        secure=settings.env == "prod",
        samesite="lax",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/register", response_model=UserProfile, status_code=201)
def register(
    body: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    """Create an unverified account and send its first code."""
    return _profile_schema(
        service.register(body.email, body.phone, body.password, body.full_name)
    )


@router.post("/auth/verify-email", response_model=UserProfile)
def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    """Consume a verification code for an email address."""
    return _profile_schema(
        service.verify_email(body.email, body.code, _client_ip(request))
    )


@router.post(
    "/auth/resend-verification", response_model=AcceptedResponse, status_code=202
)
def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AcceptedResponse:
    """Reissue a code. Silent about account existence."""
    service.resend_verification(body.email, _client_ip(request))
    return AcceptedResponse()


@router.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Check credentials and start a stateful refresh family."""
    pair = service.login(body.email, body.password, _client_ip(request))
    _write_refresh_cookie(response, pair.refresh_token, settings)
    return _token_schema(pair)


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Rotate the refresh cookie. Reuse burns the whole family."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise UnauthorizedError("Session has expired.")
    pair = service.refresh(token)
    _write_refresh_cookie(response, pair.refresh_token, settings)
    return _token_schema(pair)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Revoke one refresh token and clear its cookie."""
    service.logout(request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return response


@router.post("/auth/logout-all", status_code=204)
def logout_all(
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Revoke every refresh token of the current user."""
    service.logout_all(current.id)
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return response


@router.post(
    "/auth/forgot-password", response_model=AcceptedResponse, status_code=202
)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AcceptedResponse:
    """Issue a reset code. Silent about account existence."""
    service.forgot_password(body.email, _client_ip(request))
    return AcceptedResponse()


@router.post("/auth/reset-password", response_model=AcceptedResponse)
def reset_password(
    body: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> AcceptedResponse:
    """Consume a reset code and burn every session."""
    service.reset_password(body.email, body.code, body.new_password)
    return AcceptedResponse()


@router.post("/auth/change-password", response_model=AcceptedResponse)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> AcceptedResponse:
    """Rotate the password, sparing only the current session."""
    presented = request.cookies.get(REFRESH_COOKIE)
    service.change_password(
        current.id,
        body.current_password,
        body.new_password,
        hash_token(presented) if presented else None,
    )
    return AcceptedResponse()


@router.get("/auth/me", response_model=UserProfile)
def me(
    current: CurrentUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    """Current session profile for frontend session state."""
    return _profile_schema(service.get_profile(current.id))


@router.post("/auth/dev/challenge-code", response_model=DevChallengeResponse)
def dev_challenge_code(
    body: DevChallengeRequest,
    settings: Settings = Depends(get_settings),
    service: AuthService = Depends(get_auth_service),
) -> DevChallengeResponse:
    """Dev-only plaintext code issuance. 404 outside ENV=dev."""
    if settings.env != "dev":
        raise NotFoundError("Not found.")
    code, ttl = service.dev_challenge_code(body.email, body.kind)
    return DevChallengeResponse(
        email=body.email, kind=body.kind, code=code, expires_in_seconds=ttl
    )
