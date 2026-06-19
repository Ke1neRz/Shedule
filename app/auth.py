import hashlib
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.db import get_conn


PBKDF2_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    try:
        salt, hex_digest = stored.split("$", 1)
        expected = bytes.fromhex(hex_digest)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return secrets.compare_digest(expected, actual)


def _row_to_dict(row):
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "role": row["role"],
        "full_name": row["full_name"],
    }


async def _fetch_user_by_id(conn, user_id: int):
    return _row_to_dict(
        await conn.fetchrow(
            """
            SELECT user_id, username, role, full_name
              FROM app_user
             WHERE user_id = $1
            """,
            user_id,
        )
    )


async def get_current_user(
    request: Request, conn=Depends(get_conn)
) -> dict | None:
    user_id = request.session.get("user_id")
    if not user_id:
        request.state.user = None
        return None
    user = await _fetch_user_by_id(conn, user_id)
    request.state.user = user
    return user


async def get_current_user_from_state(request: Request) -> dict | None:
    """Берёт пользователя из request.state, который кладёт middleware.

    Используется в middleware и в зависимостях, где допустим await."""
    return getattr(request.state, "user", None)


def current_user_sync(request: Request) -> dict | None:
    """Синхронный геттер для Jinja2-глобала. Не делает запросов к БД —
    читает только из request.state.user, который кладёт middleware."""
    return getattr(request.state, "user", None)


async def login_user(request: Request, user_row) -> None:
    request.session["user_id"] = user_row["user_id"]
    request.state.user = _row_to_dict(user_row)


async def logout_user(request: Request) -> None:
    request.session.clear()
    request.state.user = None


async def authenticate(conn, username: str, password: str):
    row = await conn.fetchrow(
        """
        SELECT user_id, username, password_hash, role, full_name
          FROM app_user
         WHERE username = $1
        """,
        username,
    )
    if row is None:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return row


def _build_login_redirect(request: Request) -> RedirectResponse:
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    return RedirectResponse(
        url=f"/auth/login?next={next_url}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


class RedirectToLogin(Exception):
    """Внутренний сигнал зависимости, что нужно редиректнуть на /auth/login.

    Реальный редирект строит exception-handler в main.py — там есть доступ
    к Request и можно закодировать next-параметр из URL."""

    def __init__(self, request: Request):
        self.request = request
        self.next_url = request.url.path
        if request.url.query:
            self.next_url = f"{self.next_url}?{request.url.query}"


async def require_login(
    request: Request, user: dict | None = Depends(get_current_user)
):
    if user is None:
        raise RedirectToLogin(request)
    return user


async def require_teacher(
    request: Request, user: dict | None = Depends(get_current_user)
):
    if user is None:
        raise RedirectToLogin(request)
    if user["role"] != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Это действие доступно только преподавателям.",
        )
    return user
