from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from .metadata import shared_metadata

DEFAULT_DATABASE_URL = "postgresql://rivalens:123456@localhost:5433/rivalens"

users = Table(
    "users",
    shared_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("email", String(320), nullable=False),
    Column("display_name", String(80), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(32), nullable=False, server_default=text("'user'")),
    Column("status", String(32), nullable=False, server_default=text("'active'")),
    Column("email_verified_at", DateTime(timezone=True), nullable=True),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
)

Index("ux_users_email", users.c.email, unique=True)


class DuplicateEmailError(ValueError):
    pass


class UserStore:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        self._database_url = database_url
        self._engine = engine

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            database_url = self._database_url or os.getenv(
                "DATABASE_URL",
                DEFAULT_DATABASE_URL,
            )
            self._engine = create_engine(
                _sqlalchemy_database_url(database_url),
                pool_pre_ping=True,
            )
        return self._engine

    def initialize(self) -> None:
        shared_metadata.create_all(self.engine)

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> dict:
        now = _utcnow()
        user = {
            "id": uuid4(),
            "email": email,
            "display_name": display_name,
            "password_hash": password_hash,
            "role": "user",
            "status": "active",
            "email_verified_at": None,
            "last_login_at": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(users), user)
        except IntegrityError as exc:
            raise DuplicateEmailError("该邮箱已注册") from exc
        return user

    def get_user_by_email(self, email: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(users).where(users.c.email == email)
            ).mappings().first()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str | UUID) -> dict | None:
        try:
            normalized_id = (
                user_id if isinstance(user_id, UUID) else UUID(str(user_id))
            )
        except ValueError:
            return None

        with self.engine.connect() as connection:
            row = connection.execute(
                select(users).where(users.c.id == normalized_id)
            ).mappings().first()
        return dict(row) if row else None

    def record_successful_login(self, user_id: str | UUID) -> dict | None:
        try:
            normalized_id = (
                user_id if isinstance(user_id, UUID) else UUID(str(user_id))
            )
        except ValueError:
            return None

        now = _utcnow()
        with self.engine.begin() as connection:
            connection.execute(
                update(users)
                .where(users.c.id == normalized_id)
                .values(last_login_at=now, updated_at=now)
            )
        return self.get_user_by_id(normalized_id)

    def update_user_profile(
        self,
        user_id: str | UUID,
        *,
        display_name: str,
    ) -> dict | None:
        try:
            normalized_id = (
                user_id if isinstance(user_id, UUID) else UUID(str(user_id))
            )
        except ValueError:
            return None

        now = _utcnow()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(users)
                .where(users.c.id == normalized_id)
                .values(display_name=display_name, updated_at=now)
            )
        if result.rowcount < 1:
            return None
        return self.get_user_by_id(normalized_id)


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
