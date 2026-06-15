from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import asyncpg
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def list_teachers(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT t.*, d.name AS division_name
        FROM teacher t
        JOIN division d ON t.division_id = d.division_id
        ORDER BY t.last_name, t.first_name
        """
    )
    return templates.TemplateResponse(
        "teachers/list.html",
        {"request": request, "teachers": rows},
    )


@router.get("/add")
async def add_form(request: Request, conn=Depends(get_conn)):
    divisions = await conn.fetch(
        """
        SELECT division_id, name
        FROM division
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "teachers/form.html",
        {"request": request, "teacher": None, "divisions": divisions},
    )


@router.post("/add")
async def add_submit(
    last_name: str = Form(...),
    first_name: str = Form(...),
    middle_name: str = Form(""),
    degree: str = Form(""),
    title: str = Form(""),
    position: str = Form(""),
    email: str = Form(""),
    division_id: int = Form(...),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO teacher
            (last_name, first_name, middle_name, degree, title, position, email, division_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        last_name, first_name, middle_name, degree, title, position, email, division_id,
    )
    return RedirectResponse(url="/teachers/", status_code=303)


@router.get("/edit/{teacher_id}")
async def edit_form(request: Request, teacher_id: int, conn=Depends(get_conn)):
    teacher = await conn.fetchrow(
        """
        SELECT *
        FROM teacher
        WHERE teacher_id = $1
        """,
        teacher_id,
    )
    divisions = await conn.fetch(
        """
        SELECT division_id, name
        FROM division
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "teachers/form.html",
        {"request": request, "teacher": teacher, "divisions": divisions},
    )


@router.post("/edit/{teacher_id}")
async def edit_submit(
    teacher_id: int,
    last_name: str = Form(...),
    first_name: str = Form(...),
    middle_name: str = Form(""),
    degree: str = Form(""),
    title: str = Form(""),
    position: str = Form(""),
    email: str = Form(""),
    division_id: int = Form(...),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE teacher
           SET last_name   = $1,
               first_name  = $2,
               middle_name = $3,
               degree      = $4,
               title       = $5,
               position    = $6,
               email       = $7,
               division_id = $8
         WHERE teacher_id  = $9
        """,
        last_name, first_name, middle_name, degree, title, position, email, division_id,
        teacher_id,
    )
    return RedirectResponse(url="/teachers/", status_code=303)


@router.post("/delete/{teacher_id}")
async def delete(teacher_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM teacher
        WHERE teacher_id = $1
        """,
        teacher_id,
    )
    return RedirectResponse(url="/teachers/", status_code=303)


# Preferences
@router.get("/{teacher_id}/preferences")
async def list_preferences(request: Request, teacher_id: int, conn=Depends(get_conn)):
    teacher = await conn.fetchrow(
        """
        SELECT *
        FROM teacher
        WHERE teacher_id = $1
        """,
        teacher_id,
    )
    rows = await conn.fetch(
        """
        SELECT p.*,
               ts.day_of_week, ts.pair_number, ts.start_time, ts.end_time
        FROM teacher_preference p
        JOIN timeslot ts ON p.day_of_week = ts.day_of_week
                        AND p.pair_number = ts.pair_number
        WHERE p.teacher_id = $1
        ORDER BY p.day_of_week, p.pair_number
        """,
        teacher_id,
    )
    return templates.TemplateResponse(
        "teachers/preferences_list.html",
        {"request": request, "teacher": teacher, "preferences": rows},
    )


@router.get("/{teacher_id}/preferences/add")
async def add_preference_form(request: Request, teacher_id: int, conn=Depends(get_conn)):
    teacher = await conn.fetchrow(
        """
        SELECT *
        FROM teacher
        WHERE teacher_id = $1
        """,
        teacher_id,
    )
    timeslots = await conn.fetch(
        """
        SELECT *
        FROM timeslot
        ORDER BY day_of_week, pair_number
        """
    )
    return templates.TemplateResponse(
        "teachers/preference_form.html",
        {
            "request": request,
            "teacher": teacher,
            "preference": None,
            "timeslots": timeslots,
        },
    )


@router.post("/{teacher_id}/preferences/add")
async def add_preference_submit(
    teacher_id: int,
    day_of_week: int = Form(...),
    pair_number: int = Form(...),
    is_preferred: bool = Form(False),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO teacher_preference
            (teacher_id, day_of_week, pair_number, is_preferred)
        VALUES ($1, $2, $3, $4)
        """,
        teacher_id, day_of_week, pair_number, is_preferred,
    )
    return RedirectResponse(
        url=f"/teachers/{teacher_id}/preferences", status_code=303
    )


@router.get("/{teacher_id}/preferences/edit/{preference_id}")
async def edit_preference_form(
    request: Request, teacher_id: int, preference_id: int, conn=Depends(get_conn)
):
    teacher = await conn.fetchrow(
        """
        SELECT *
        FROM teacher
        WHERE teacher_id = $1
        """,
        teacher_id,
    )
    preference = await conn.fetchrow(
        """
        SELECT *
        FROM teacher_preference
        WHERE preference_id = $1
        """,
        preference_id,
    )
    timeslots = await conn.fetch(
        """
        SELECT *
        FROM timeslot
        ORDER BY day_of_week, pair_number
        """
    )
    return templates.TemplateResponse(
        "teachers/preference_form.html",
        {
            "request": request,
            "teacher": teacher,
            "preference": preference,
            "timeslots": timeslots,
        },
    )


@router.post("/{teacher_id}/preferences/edit/{preference_id}")
async def edit_preference_submit(
    teacher_id: int,
    preference_id: int,
    day_of_week: int = Form(...),
    pair_number: int = Form(...),
    is_preferred: bool = Form(False),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE teacher_preference
           SET day_of_week   = $1,
               pair_number   = $2,
               is_preferred  = $3
         WHERE preference_id = $4
        """,
        day_of_week, pair_number, is_preferred, preference_id,
    )
    return RedirectResponse(
        url=f"/teachers/{teacher_id}/preferences", status_code=303
    )


@router.post("/{teacher_id}/preferences/delete/{preference_id}")
async def delete_preference(teacher_id: int, preference_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM teacher_preference
        WHERE preference_id = $1
        """,
        preference_id,
    )
    return RedirectResponse(
        url=f"/teachers/{teacher_id}/preferences", status_code=303
    )
