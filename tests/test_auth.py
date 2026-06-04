import os
import unittest
from unittest.mock import patch

from fastapi import WebSocket
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.server import app as app_module
from server.auth import (
    AUTH_COOKIE_NAME,
    AuthConfig,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from server.trace_store import TraceStore
from server.user_store import UserStore, metadata


class AuthSecurityTest(unittest.TestCase):
    def test_password_hash_never_contains_plaintext_password(self):
        password = "correct-horse-battery-staple"

        encoded = hash_password(password)

        self.assertNotIn(password, encoded)
        self.assertTrue(verify_password(password, encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_access_token_rejects_wrong_secret(self):
        token, _ = create_access_token(
            "user-id",
            config=AuthConfig(jwt_secret="a" * 32, access_token_ttl_seconds=3600),
        )

        with self.assertRaises(InvalidTokenError):
            decode_access_token(
                token,
                config=AuthConfig(
                    jwt_secret="b" * 32,
                    access_token_ttl_seconds=3600,
                ),
            )


class AuthApiTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.store = UserStore(engine=engine)
        self.trace_store = TraceStore(engine=engine)
        self.store.initialize()
        self.trace_store.initialize()
        self.store_patch = patch.object(app_module, "user_store", self.store)
        self.trace_store_patch = patch.object(
            app_module,
            "trace_store",
            self.trace_store,
        )
        self.secret_patch = patch.dict(os.environ, {"AUTH_JWT_SECRET": "x" * 32})
        self.store_patch.start()
        self.trace_store_patch.start()
        self.secret_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        self.client.close()
        self.secret_patch.stop()
        self.trace_store_patch.stop()
        self.store_patch.stop()

    def test_auth_metadata_only_contains_users_table(self):
        self.assertEqual(set(metadata.tables), {"users"})

    def test_register_login_and_current_user(self):
        register_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "Analyst@Example.com",
                "password": "strong-password",
                "display_name": "Analyst",
            },
        )

        self.assertEqual(register_response.status_code, 201)
        register_body = register_response.json()
        self.assertEqual(register_body["user"]["email"], "analyst@example.com")
        self.assertNotIn("password_hash", register_body["user"])

        stored_user = self.store.get_user_by_email("analyst@example.com")
        self.assertIsNotNone(stored_user)
        self.assertNotEqual(stored_user["password_hash"], "strong-password")

        duplicate_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "ANALYST@example.com",
                "password": "another-password",
                "display_name": "Other Analyst",
            },
        )
        self.assertEqual(duplicate_response.status_code, 409)

        wrong_login_response = self.client.post(
            "/api/auth/login",
            json={
                "email": "analyst@example.com",
                "password": "wrong-password",
            },
        )
        self.assertEqual(wrong_login_response.status_code, 401)

        login_response = self.client.post(
            "/api/auth/login",
            json={
                "email": "analyst@example.com",
                "password": "strong-password",
            },
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["access_token"]

        current_user_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(current_user_response.status_code, 200)
        self.assertEqual(
            current_user_response.json()["email"],
            "analyst@example.com",
        )

    def test_current_user_requires_bearer_token(self):
        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 401)

    def test_trace_run_requires_owner_or_admin(self):
        owner_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "owner@example.com",
                "password": "strong-password",
                "display_name": "Owner",
            },
        )
        owner = owner_response.json()
        self.trace_store.persist_state(
            {
                "task": {"run_id": "owned_run", "query": "Compare products"},
                "report": "Owned report",
            },
            user_id=owner["user"]["id"],
        )

        owner_trace_response = self.client.get(
            "/api/trace/runs/owned_run",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
        )
        self.assertEqual(owner_trace_response.status_code, 200)

        other_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "other@example.com",
                "password": "strong-password",
                "display_name": "Other",
            },
        ).json()
        other_trace_response = self.client.get(
            "/api/trace/runs/owned_run",
            headers={"Authorization": f"Bearer {other_response['access_token']}"},
        )
        self.assertEqual(other_trace_response.status_code, 404)

    def test_websocket_cookie_resolves_current_user(self):
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": "socket@example.com",
                "password": "strong-password",
                "display_name": "Socket User",
            },
        ).json()
        websocket = WebSocket(
            {
                "type": "websocket",
                "headers": [
                    (
                        b"cookie",
                        f"{AUTH_COOKIE_NAME}={response['access_token']}".encode(),
                    )
                ],
            },
            receive=lambda: None,
            send=lambda message: None,
        )

        user = app_module._optional_websocket_user(websocket)

        self.assertEqual(str(user["id"]), response["user"]["id"])


if __name__ == "__main__":
    unittest.main()
