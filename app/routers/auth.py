from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette import status

from app.auth import (
    authenticate,
    get_current_user,
    hash_password,
    login_user,
    logout_user,
)
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


def _safe_next(next_url: str | None) -> str:
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


@router.get("/login")
async def login_form(
    request: Request,
    next: str = Query("/"),
    user=Depends(get_current_user),
):
    if user:
        return RedirectResponse(url=_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "next": _safe_next(next), "error": None,
         "username": ""},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    conn=Depends(get_conn),
):
    row = await authenticate(conn, username.strip(), password)
    if row is None:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "next": _safe_next(next),
             "error": "Неверный логин или пароль.", "username": username},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    await login_user(request, row)
    return RedirectResponse(
        url=_safe_next(next), status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/register")
async def register_form(
    request: Request,
    user=Depends(get_current_user),
):
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "error": None,
         "form": {"username": "", "full_name": "", "role": "student"}},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    full_name: str = Form(""),
    role: str = Form("student"),
    conn=Depends(get_conn),
):
    username = username.strip()
    form = {"username": username, "full_name": full_name.strip(), "role": role}

    if len(username) < 3 or len(username) > 50:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Логин должен быть от 3 до 50 символов.",
             "form": form},
            status_code=400,
        )
    if not username.replace("_", "").replace("-", "").isalnum():
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Логин может содержать только буквы, "
                                          "цифры, _ и -.",
             "form": form},
            status_code=400,
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Пароль должен быть не короче 6 символов.",
             "form": form},
            status_code=400,
        )
    if password != password_confirm:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Пароли не совпадают.", "form": form},
            status_code=400,
        )
    if role not in ("student", "teacher"):
        role = "student"

    exists = await conn.fetchval(
        "SELECT 1 FROM app_user WHERE username = $1", username,
    )
    if exists:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Пользователь с таким логином уже существует.",
             "form": form},
            status_code=400,
        )

    pwd_hash = hash_password(password)
    row = await conn.fetchrow(
        """
        INSERT INTO app_user (username, password_hash, role, full_name)
        VALUES ($1, $2, $3, $4)
        RETURNING user_id, username, role, full_name
        """,
        username, pwd_hash, role, full_name.strip() or None,
    )
    await login_user(request, row)
    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    await logout_user(request)
    return RedirectResponse(url="/", status_code=303)
