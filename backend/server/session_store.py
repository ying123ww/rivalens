from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Uuid,
    cast,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from .metadata import shared_metadata
from .user_store import DEFAULT_DATABASE_URL, users

logger = logging.getLogger(__name__)

SESSION_PERSISTENCE_ENABLED_ENV = "RIVALENS_SESSION_PERSISTENCE_ENABLED"
DEFAULT_REDIS_URL = "redis://:123456@localhost:6380/0"
SESSION_REDIS_TTL_SECONDS = 1800  # 30 minutes
SESSION_SIDEBAR_LIMIT = 10
STREAM_MAXLEN = 500

JSON_DATA = JSON().with_variant(JSONB, "postgresql")

chat_sessions = Table(
    "chat_sessions",
    shared_metadata,
    Column("session_id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
    Column(
        "user_id",
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("title", String(200), nullable=False, default="新对话"),
    Column("memory", JSON_DATA, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("ix_chat_sessions_user_id", chat_sessions.c.user_id)
Index("ix_chat_sessions_user_updated", chat_sessions.c.user_id, chat_sessions.c.updated_at.desc())

# ── Lua scripts ───────────────────────────────────────────────────
# All scripts use KEYS for Redis keys and ARGV for values so that
# key names are computed once in Python and passed in.

_LUA_CACHE_META = """
-- Atomic: HSET meta + EXPIRE meta + ZADD order
-- KEYS[1]: meta key   KEYS[2]: order key
-- ARGV[1]: session_id   ARGV[2]: user_id   ARGV[3]: title
-- ARGV[4]: created_at   ARGV[5]: updated_at   ARGV[6]: TTL seconds
redis.call('HSET', KEYS[1],
    'session_id', ARGV[1],
    'user_id', ARGV[2],
    'title', ARGV[3],
    'created_at', ARGV[4],
    'updated_at', ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[6])
local now = redis.call('TIME')
redis.call('ZADD', KEYS[2], now[1], ARGV[1])
return 1
"""

_LUA_REFRESH_TTL = """
-- Atomic: EXPIRE stream + EXPIRE meta
-- KEYS[1]: stream key   KEYS[2]: meta key
-- ARGV[1]: TTL seconds
redis.call('EXPIRE', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[2], ARGV[1])
return 1
"""

_LUA_APPEND_MESSAGE = """
-- Atomic: XADD stream + HSET meta.updated_at + EXPIRE meta + ZADD order
-- KEYS[1]: stream key   KEYS[2]: meta key   KEYS[3]: order key
-- ARGV[1]: maxlen (~N)   ARGV[2]: TTL seconds   ARGV[3]: updated_at (iso)
-- ARGV[4..N]: message fields as key1, val1, key2, val2, ...
local maxlen = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local updated_at = ARGV[3]

-- XADD with MAXLEN
local entry_id = redis.call('XADD', KEYS[1], 'MAXLEN', '~', maxlen, '*', unpack(ARGV, 4))

-- Update meta
redis.call('HSET', KEYS[2], 'updated_at', updated_at)
redis.call('EXPIRE', KEYS[2], ttl)
redis.call('EXPIRE', KEYS[1], ttl)

-- Touch order
local now = redis.call('TIME')
redis.call('ZADD', KEYS[3], now[1], redis.call('HGET', KEYS[2], 'session_id'))

return entry_id
"""

_LUA_DELETE_SESSION_KEYS = """
-- Atomic: DEL stream + DEL meta + (optionally) ZREM order
-- KEYS[1]: stream key   KEYS[2]: meta key   KEYS[3]: order key
if redis.call('EXISTS', KEYS[1]) + redis.call('EXISTS', KEYS[2]) == 0 then
    return 0
end
local meta = redis.call('HGETALL', KEYS[2])
redis.call('DEL', KEYS[1], KEYS[2])
-- Only ZREM if we actually have the session_id to remove
local sid = nil
for i = 1, #meta, 2 do
    if meta[i] == 'session_id' then
        sid = meta[i + 1]
        break
    end
end
if sid then
    redis.call('ZREM', KEYS[3], sid)
end
return 1
"""


class SessionStore:
    def __init__(
        self,
        database_url: str | None = None,
        redis_url: str | None = None,
    ) -> None:
        self._database_url = database_url
        self._redis_url = redis_url
        self._engine: Engine | None = None
        self._redis: Any = None
        self._redis_init_attempted = False
        self._scripts: dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return _env_flag(SESSION_PERSISTENCE_ENABLED_ENV, default=True)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            database_url = self._database_url or os.getenv(
                "DATABASE_URL", DEFAULT_DATABASE_URL
            )
            self._engine = create_engine(
                _sqlalchemy_database_url(database_url),
                pool_pre_ping=True,
            )
        return self._engine

    @property
    def redis(self) -> Any | None:
        if not self.enabled or self._redis_init_attempted:
            return self._redis
        self._redis_init_attempted = True
        redis_url = self._redis_url or os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        try:
            import redis as _redis

            self._redis = _redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            self._register_scripts()
        except Exception:
            logger.warning("Redis unavailable, falling back to PostgreSQL only")
            self._redis = None
        return self._redis

    def _register_scripts(self) -> None:
        """Pre-load Lua scripts for EVALSHA reuse."""
        r = self._redis
        self._scripts["cache_meta"] = r.register_script(_LUA_CACHE_META)
        self._scripts["refresh_ttl"] = r.register_script(_LUA_REFRESH_TTL)
        self._scripts["append"] = r.register_script(_LUA_APPEND_MESSAGE)
        self._scripts["delete_keys"] = r.register_script(_LUA_DELETE_SESSION_KEYS)

    def initialize(self) -> None:
        shared_metadata.create_all(self.engine)

    # ── Redis key helpers ──────────────────────────────────────────

    @staticmethod
    def _stream_key(session_id: str) -> str:
        return f"chat:session:{session_id}:stream"

    @staticmethod
    def _meta_key(session_id: str) -> str:
        return f"chat:session:{session_id}:meta"

    @staticmethod
    def _order_key(user_id: str) -> str:
        return f"chat:sessions:user:{user_id}:order"

    # ── Public API ─────────────────────────────────────────────────

    def create_session(
        self, user_id: str | UUID, title: str = "新对话"
    ) -> dict[str, Any]:
        sid = uuid4()
        now = _utcnow()
        row = {
            "session_id": sid,
            "user_id": user_id,
            "title": title,
            "memory": [],
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            conn.execute(insert(chat_sessions), row)

        session = _to_response(dict(row))
        self._cache_session(session)
        return session

    def get_sidebar_sessions(
        self, user_id: str | UUID, limit: int = SESSION_SIDEBAR_LIMIT
    ) -> list[dict[str, Any]]:
        uid = str(user_id)
        r = self.redis

        if r:
            order_key = self._order_key(uid)
            all_members = r.zrevrange(order_key, 0, -1)
            sessions: list[dict[str, Any]] = []
            stale: list[str] = []

            for sid in all_members:
                if len(sessions) >= limit:
                    break
                meta = r.hgetall(self._meta_key(sid))
                if meta:
                    sessions.append(meta)
                else:
                    stale.append(sid)

            if stale:
                r.zrem(order_key, *stale)

            if len(sessions) >= limit:
                return sessions

            exclude = {s["session_id"] for s in sessions}
            pg_sessions = self._pg_get_sessions(uid, limit - len(sessions), exclude)
            for s in pg_sessions:
                self._cache_session(s)
            return sessions + pg_sessions

        return self._pg_get_sessions(uid, limit)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        r = self.redis

        if r:
            meta = r.hgetall(self._meta_key(session_id))
            if meta:
                messages = self._stream_read(r, session_id)
                meta["memory"] = messages
                self._refresh_ttl(session_id)
                return meta

        row = self._pg_get_row(session_id)
        if row is None:
            return None
        session = _to_response(row)
        self._cache_session(session)
        return session

    def update_session_memory(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> None:
        now = _utcnow()

        with self.engine.begin() as conn:
            conn.execute(
                update(chat_sessions)
                .where(chat_sessions.c.session_id == session_id)
                .values(memory=messages, updated_at=now)
            )

        r = self.redis
        if r:
            try:
                self._stream_replace(r, session_id, messages)
                r.hset(self._meta_key(session_id), "updated_at", now.isoformat())
                r.expire(self._meta_key(session_id), SESSION_REDIS_TTL_SECONDS)
                self._touch_order(r, session_id)
            except Exception:
                logger.warning("Redis cache write failed for session %s", session_id)

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        """PG first (source of truth), then Redis (best-effort cache)."""
        now = _utcnow()

        self._pg_append(session_id, message, now)

        r = self.redis
        if r:
            try:
                fields = _message_to_fields(message)
                argv = [
                    str(STREAM_MAXLEN),
                    str(SESSION_REDIS_TTL_SECONDS),
                    now.isoformat(),
                ]
                for k, v in fields.items():
                    argv.extend([k, v])

                self._scripts["append"](
                    keys=[
                        self._stream_key(session_id),
                        self._meta_key(session_id),
                        self._order_key(self._resolve_user_id(r, session_id) or ""),
                    ],
                    args=argv,
                )
            except Exception:
                logger.warning("Redis append failed for session %s", session_id)

    def update_session_meta(self, session_id: str, **kwargs: Any) -> None:
        now = _utcnow()
        r = self.redis

        if r:
            try:
                redis_meta = {k: v for k, v in kwargs.items() if v is not None}
                redis_meta["updated_at"] = now.isoformat()
                r.hset(self._meta_key(session_id), mapping=redis_meta)
                r.expire(self._meta_key(session_id), SESSION_REDIS_TTL_SECONDS)
            except Exception:
                logger.warning("Redis meta update failed for %s", session_id)

        pg_values = {k: v for k, v in kwargs.items() if k in {"title"}}
        if pg_values:
            pg_values["updated_at"] = now
            with self.engine.begin() as conn:
                conn.execute(
                    update(chat_sessions)
                    .where(chat_sessions.c.session_id == session_id)
                    .values(**pg_values)
                )

    def delete_session(self, session_id: str) -> bool:
        r = self.redis

        with self.engine.begin() as conn:
            result = conn.execute(
                delete(chat_sessions).where(
                    chat_sessions.c.session_id == session_id
                )
            )
            if result.rowcount == 0:
                return False

        if r:
            try:
                uid = self._resolve_user_id(r, session_id) or ""
                self._scripts["delete_keys"](
                    keys=[
                        self._stream_key(session_id),
                        self._meta_key(session_id),
                        self._order_key(uid),
                    ],
                    args=[],
                )
            except Exception:
                logger.warning("Redis cleanup failed for session %s", session_id)

        return True

    # ── Internal helpers ───────────────────────────────────────────

    def _resolve_user_id(self, r: Any, session_id: str) -> str | None:
        """Try meta first, then PG. Returns user_id string or None."""
        meta = r.hgetall(self._meta_key(session_id))
        if meta and meta.get("user_id"):
            return str(meta["user_id"])
        row = self._pg_get_row(session_id)
        return str(row["user_id"]) if row else None

    def _pg_append(
        self, session_id: str, message: dict[str, Any], now: datetime
    ) -> None:
        msg_json = json.dumps(message, ensure_ascii=False)
        with self.engine.begin() as conn:
            conn.execute(
                update(chat_sessions)
                .where(chat_sessions.c.session_id == session_id)
                .values(
                    memory=chat_sessions.c.memory.op("||")(cast(msg_json, JSONB)),
                    updated_at=now,
                )
            )

    def _stream_read(self, r: Any, session_id: str) -> list[dict[str, Any]]:
        entries = r.xrevrange(
            self._stream_key(session_id), "+", "-", count=STREAM_MAXLEN
        )
        entries.reverse()
        return [_fields_to_message(fields) for _, fields in entries]

    def _stream_replace(
        self, r: Any, session_id: str, messages: list[dict[str, Any]]
    ) -> None:
        stream_key = self._stream_key(session_id)
        msgs = messages[-STREAM_MAXLEN:]
        pipe = r.pipeline()
        pipe.delete(stream_key)
        for msg in msgs:
            pipe.xadd(
                stream_key,
                _message_to_fields(msg),
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        pipe.expire(stream_key, SESSION_REDIS_TTL_SECONDS)
        pipe.execute()

    def _pg_get_sessions(
        self,
        user_id: str,
        limit: int,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(chat_sessions)
            .where(chat_sessions.c.user_id == user_id)
            .order_by(chat_sessions.c.updated_at.desc())
            .limit(limit + (len(exclude) if exclude else 0) + SESSION_SIDEBAR_LIMIT)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()

        results: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            if exclude and str(d["session_id"]) in exclude:
                continue
            results.append(_to_response(d))
            if len(results) >= limit:
                break
        return results

    def _pg_get_row(self, session_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(chat_sessions).where(
                    chat_sessions.c.session_id == session_id
                )
            ).mappings().first()
        return dict(row) if row else None

    def _cache_session(self, session: dict[str, Any]) -> None:
        r = self.redis
        if r is None:
            return

        sid = session["session_id"]
        uid = str(session.get("user_id", ""))
        memory = session.get("memory", [])

        try:
            self._scripts["cache_meta"](
                keys=[self._meta_key(sid), self._order_key(uid)],
                args=[
                    sid,
                    uid,
                    session.get("title", "新对话"),
                    session.get("created_at", ""),
                    session.get("updated_at", ""),
                    str(SESSION_REDIS_TTL_SECONDS),
                ],
            )

            if memory:
                self._stream_replace(r, sid, memory)
        except Exception:
            logger.warning("Redis cache write failed for session %s", sid)

    def _touch_order(
        self, r: Any, session_id: str, user_id: str | None = None
    ) -> None:
        if user_id is None:
            meta = r.hgetall(self._meta_key(session_id))
            user_id = meta.get("user_id", "")
            if not user_id:
                return
        r.zadd(self._order_key(str(user_id)), {session_id: time.time()})

    def _refresh_ttl(self, session_id: str) -> None:
        r = self.redis
        if r is None:
            return
        try:
            self._scripts["refresh_ttl"](
                keys=[self._stream_key(session_id), self._meta_key(session_id)],
                args=[str(SESSION_REDIS_TTL_SECONDS)],
            )
        except Exception:
            pass


# ── Message serialization helpers ─────────────────────────────────

def _message_to_fields(msg: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for k, v in msg.items():
        if isinstance(v, str):
            fields[k] = v
        elif v is not None:
            fields[k] = json.dumps(v, ensure_ascii=False)
    return fields


def _fields_to_message(fields: dict[str, str]) -> dict[str, Any]:
    msg: dict[str, Any] = {}
    for k, v in fields.items():
        if v.startswith("{") or v.startswith("["):
            try:
                msg[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                msg[k] = v
        elif v.isdigit():
            msg[k] = int(v)
        else:
            msg[k] = v
    return msg


def _to_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": str(data.get("session_id", "")),
        "user_id": str(data.get("user_id", "")),
        "title": data.get("title", "新对话"),
        "memory": data.get("memory", []),
        "created_at": _iso(data.get("created_at")),
        "updated_at": _iso(data.get("updated_at")),
    }


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
