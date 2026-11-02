"""Routes for passwords, email verification, and the account profile."""

from fastapi import APIRouter, BackgroundTasks, status

from src.auth import accounts, recovery
from src.auth.deps import Client, Config, CurrentPrincipal, Db, MailerDep
from src.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ProfileUpdateRequest,
    ResetPasswordRequest,
    UserResponse,
    VerifyEmailRequest,
)

router = APIRouter(tags=["account"])


@router.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Db,
    settings: Config,
    client: Client,
    mailer: MailerDep,
    background: BackgroundTasks,
) -> None:
    recovery.request_password_reset(
        db, payload.email, settings, client, mailer, background
    )


@router.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, db: Db) -> None:
    recovery.reset_password(db, payload.token, payload.new_password)


@router.post("/auth/password/change", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest, principal: CurrentPrincipal, db: Db
) -> None:
    recovery.change_password(
        db, principal, payload.current_password, payload.new_password
    )


@router.post("/auth/email/verify", status_code=status.HTTP_204_NO_CONTENT)
def verify_email(payload: VerifyEmailRequest, db: Db) -> None:
    recovery.verify_email(db, payload.token)


@router.post("/auth/email/resend", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    principal: CurrentPrincipal,
    db: Db,
    settings: Config,
    mailer: MailerDep,
    background: BackgroundTasks,
) -> None:
    recovery.resend_verification(db, principal.user, settings, mailer, background)


@router.get("/account/me")
def get_me(principal: CurrentPrincipal) -> UserResponse:
    return UserResponse.model_validate(principal.user)


@router.patch("/account/me")
def update_me(
    payload: ProfileUpdateRequest, principal: CurrentPrincipal, db: Db
) -> UserResponse:
    user = accounts.update_profile(db, principal.user, payload)
    return UserResponse.model_validate(user)
