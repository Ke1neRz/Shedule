from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import RedirectToLogin
from app.config import settings
from app.db import get_pool, close_pool
from app.routers import (
    auth,
    calendar,
    curriculum,
    divisions,
    groups,
    reports,
    rooms,
    schedule,
    teachers,
    timeslots,
    universities,
)

app = FastAPI(title="Расписание учебных занятий")


@app.exception_handler(RedirectToLogin)
async def redirect_to_login_handler(request: Request, exc: RedirectToLogin):
    return RedirectResponse(
        url=f"/auth/login?next={exc.next_url}",
        status_code=303,
    )


@app.on_event("startup")
async def startup():
    await get_pool()


@app.on_event("shutdown")
async def shutdown():
    await close_pool()


@app.middleware("http")
async def load_current_user(request: Request, call_next):
    """Подтягивает пользователя из БД по session['user_id'] и кладёт в
    request.state.user, чтобы шаблоны и роуты могли использовать его без
    дополнительного запроса."""
    request.state.user = None
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if user_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, username, role, full_name
                  FROM app_user
                 WHERE user_id = $1
                """,
                user_id,
            )
            if row:
                request.state.user = {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "role": row["role"],
                    "full_name": row["full_name"],
                }
    return await call_next(request)


app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                   session_cookie="schedule_session",
                   max_age=60 * 60 * 24 * 7)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return RedirectResponse(url="/", status_code=303)


@app.get("/")
async def index(request: Request):
    return RedirectResponse(url="/schedule/", status_code=303)


app.include_router(auth.router, prefix="/auth", tags=["Авторизация"])
app.include_router(divisions.router, prefix="/divisions", tags=["Подразделения"])
app.include_router(teachers.router, prefix="/teachers", tags=["Преподаватели"])
app.include_router(curriculum.router, prefix="/curriculum", tags=["Учебные планы"])
app.include_router(groups.router, prefix="/groups", tags=["Группы"])
app.include_router(rooms.router, prefix="/rooms", tags=["Помещения"])
app.include_router(timeslots.router, prefix="/timeslots", tags=["Пары"])
app.include_router(calendar.router, prefix="/calendar", tags=["Календарь"])
app.include_router(schedule.router, prefix="/schedule", tags=["Расписание"])
app.include_router(reports.router, prefix="/reports", tags=["Отчёты"])
app.include_router(universities.router, prefix="/universities", tags=["Университеты"])
