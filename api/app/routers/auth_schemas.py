"""Request and response schemas for authentication routes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class SignupRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, max_length=72, description="Password (8–72 characters)")


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., max_length=72, description="Password")
    remember_me: bool = Field(default=False, description="Issue a long-lived token (30 days)")


class TokenResponse(BaseModel):
    model_config = _ALIAS_CFG

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer")
    role: str = Field(..., description="User role")


class MeResponse(BaseModel):
    model_config = _ALIAS_CFG

    id: int | None = Field(None, description="User ID (null for guests)")
    email: str | None = Field(None, description="User email (null for guests)")
    role: str = Field(..., description="Current role: guest, user, or admin")


class UpdateEmailRequest(BaseModel):
    email: EmailStr = Field(..., description="New email address")
    password: str = Field(..., max_length=72, description="Current password for verification")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=72, description="Current password")
    new_password: str = Field(..., min_length=8, max_length=72, description="New password (8–72 characters)")


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., max_length=72, description="Current password for verification")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email address")
    redirect_url: str | None = Field(
        None,
        description="Base URL for the reset link (must be an allowed origin). Defaults to FRONTEND_URL.",
    )


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, max_length=72, description="New password (8–72 characters)")


class MagicLinkRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email address")
    redirect_url: str | None = Field(
        None,
        description="Base URL for the magic link (must be an allowed origin). Defaults to FRONTEND_URL.",
    )


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(..., description="Magic link token from email")
