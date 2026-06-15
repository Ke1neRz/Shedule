from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def list_calendar(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT *
        FROM work_calendar
        ORDER BY calendar_date
        """
    )
    return templates.TemplateResponse(
        "calendar/list.html",
        {"request": request, "dates": rows},
    )


@router.get("/add")
async def add_form(request: Request):
    return templates.TemplateResponse(
        "calendar/form.html",
        {"request": request, "item": None},
    )


@router.post("/add")
async def add_submit(
    calendar_date: str = Form(...),
    is_working: bool = Form(False),
    is_holiday: bool = Form(False),
    note: str = Form(""),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO work_calendar (calendar_date, is_working, is_holiday, note)
        VALUES ($1, $2, $3, $4)
        """,
        calendar_date, is_working, is_holiday, note,
    )
    return RedirectResponse(url="/calendar/", status_code=303)


@router.get("/edit/{calendar_id}")
async def edit_form(request: Request, calendar_id: int, conn=Depends(get_conn)):
    item = await conn.fetchrow(
        """
        SELECT *
        FROM work_calendar
        WHERE calendar_id = $1
        """,
        calendar_id,
    )
    return templates.TemplateResponse(
        "calendar/form.html",
        {"request": request, "item": item},
    )


@router.post("/edit/{calendar_id}")
async def edit_submit(
    calendar_id: int,
    calendar_date: str = Form(...),
    is_working: bool = Form(False),
    is_holiday: bool = Form(False),
    note: str = Form(""),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE work_calendar
           SET calendar_date = $1,
               is_working    = $2,
               is_holiday    = $3,
               note          = $4
         WHERE calendar_id   = $5
        """,
        calendar_date, is_working, is_holiday, note, calendar_id,
    )
    return RedirectResponse(url="/calendar/", status_code=303)


@router.post("/delete/{calendar_id}")
async def delete(calendar_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM work_calendar
        WHERE calendar_id = $1
        """,
        calendar_id,
    )
    return RedirectResponse(url="/calendar/", status_code=303)
