from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.db import get_pool, close_pool
from app.routers import divisions, teachers, curriculum, groups, rooms, timeslots, calendar, schedule, reports, universities

app = FastAPI(title="Расписание учебных занятий")

@app.on_event("startup")
async def startup():
    await get_pool()

@app.on_event("shutdown")
async def shutdown():
    await close_pool()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

@app.get("/")
async def index(request: Request):
    return RedirectResponse(url="/schedule/", status_code=303)

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
