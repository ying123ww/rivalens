from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


DEFAULT_AUTH_JWT_SECRET = "rivalens-local-development-secret-change-before-production"
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24
JWT_ISSUER = "rivalens"
AUTH_COOKIE_NAME = "rivalens_access_token"
PASSWORD_HASH_NAME = "scrypt"
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_SALT_BYTES = 16
PASSWORD_DERIVED_KEY_BYTES = 64
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvalidTokenError(ValueError):
    pass


@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: str
    access_token_ttl_seconds: int


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        validate_password_strength(value.get_secret_value())
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: SecretStr) -> SecretStr:
        length = len(value.get_secret_value())
        if length < 1 or length > 128:
            raise ValueError("邮箱或密码错误")
        return value


class UpdateCurrentUserRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=80)


class UserPublic(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    status: str
    email_verified_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


def get_auth_config() -> AuthConfig:
    raw_ttl = os.getenv(
        "AUTH_ACCESS_TOKEN_TTL_SECONDS",
        str(DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
    )
    try:
        ttl = max(60, int(raw_ttl))
    except ValueError:
        ttl = DEFAULT_ACCESS_TOKEN_TTL_SECONDS

    return AuthConfig(
        jwt_secret=os.getenv("AUTH_JWT_SECRET", DEFAULT_AUTH_JWT_SECRET),
        access_token_ttl_seconds=ttl,
    )


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 320 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("请输入有效的邮箱地址")
    return normalized


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")
    if len(password) > 128:
        raise ValueError("密码不能超过 128 个字符")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_DERIVED_KEY_BYTES,
        maxmem=64 * 1024 * 1024,
    )
    return "$".join(
        (
            PASSWORD_HASH_NAME,
            str(PASSWORD_SCRYPT_N),
            str(PASSWORD_SCRYPT_R),
            str(PASSWORD_SCRYPT_P),
            _base64url_encode(salt),
            _base64url_encode(digest),
        )
    )


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = (
            encoded_password.split("$")
        )
        if algorithm != PASSWORD_HASH_NAME:
            return False
        salt = _base64url_decode(raw_salt)
        expected_digest = _base64url_decode(raw_digest)
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected_digest),
            maxmem=64 * 1024 * 1024,
        )
    except (TypeError, ValueError):
        return False
    return secrets.compare_digest(actual_digest, expected_digest)


def create_access_token(
    user_id: str,
    *,
    config: AuthConfig | None = None,
) -> tuple[str, int]:
    auth_config = config or get_auth_config()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + auth_config.access_token_ttl_seconds,
        "iss": JWT_ISSUER,
        "type": "access",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        (
            _base64url_encode(_json_bytes(header)),
            _base64url_encode(_json_bytes(payload)),
        )
    )
    signature = hmac.new(
        auth_config.jwt_secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return (
        f"{signing_input}.{_base64url_encode(signature)}",
        auth_config.access_token_ttl_seconds,
    )


def decode_access_token(
    token: str,
    *,
    config: AuthConfig | None = None,
) -> dict[str, Any]:
    auth_config = config or get_auth_config()
    try:
        raw_header, raw_payload, raw_signature = token.split(".")
        signing_input = f"{raw_header}.{raw_payload}"
        expected_signature = hmac.new(
            auth_config.jwt_secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signature = _base64url_decode(raw_signature)
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidTokenError("无效的访问令牌")

        header = json.loads(_base64url_decode(raw_header))
        payload = json.loads(_base64url_decode(raw_payload))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("无效的访问令牌") from exc

    if header.get("alg") != "HS256":
        raise InvalidTokenError("无效的访问令牌")
    if payload.get("iss") != JWT_ISSUER or payload.get("type") != "access":
        raise InvalidTokenError("无效的访问令牌")
    if not isinstance(payload.get("sub"), str):
        raise InvalidTokenError("无效的访问令牌")
    if not isinstance(payload.get("exp"), int) or payload["exp"] <= int(time.time()):
        raise InvalidTokenError("访问令牌已过期")
    return payload


def to_public_user(user: dict[str, Any]) -> UserPublic:
    return UserPublic(
        id=str(user["id"]),
        email=str(user["email"]),
        display_name=str(user["display_name"]),
        role=str(user["role"]),
        status=str(user["status"]),
        email_verified_at=user.get("email_verified_at"),
        last_login_at=user.get("last_login_at"),
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
