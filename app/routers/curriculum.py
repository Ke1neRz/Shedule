from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import asyncpg
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def list_curriculum(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT *
        FROM curriculum
        ORDER BY academic_year DESC, semester
        """
    )
    return templates.TemplateResponse(
        "curriculum/list.html",
        {"request": request, "curricula": rows},
    )


@router.get("/add")
async def add_form(request: Request):
    return templates.TemplateResponse(
        "curriculum/form.html",
        {"request": request, "curriculum": None},
    )


@router.post("/add")
async def add_submit(
    name: str = Form(...),
    direction_code: str = Form(""),
    semester: int = Form(...),
    academic_year: int = Form(...),
    weeks: int = Form(18),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO curriculum (name, direction_code, semester, academic_year, weeks)
        VALUES ($1, $2, $3, $4, $5)
        """,
        name, direction_code, semester, academic_year, weeks,
    )
    return RedirectResponse(url="/curriculum/", status_code=303)


@router.get("/edit/{curriculum_id}")
async def edit_form(request: Request, curriculum_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT *
        FROM curriculum
        WHERE curriculum_id = $1
        """,
        curriculum_id,
    )
    return templates.TemplateResponse(
        "curriculum/form.html",
        {"request": request, "curriculum": row},
    )


@router.post("/edit/{curriculum_id}")
async def edit_submit(
    curriculum_id: int,
    name: str = Form(...),
    direction_code: str = Form(""),
    semester: int = Form(...),
    academic_year: int = Form(...),
    weeks: int = Form(18),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE curriculum
           SET name          = $1,
               direction_code = $2,
               semester      = $3,
               academic_year = $4,
               weeks         = $5
         WHERE curriculum_id = $6
        """,
        name, direction_code, semester, academic_year, weeks, curriculum_id,
    )
    return RedirectResponse(url="/curriculum/", status_code=303)


@router.post("/delete/{curriculum_id}")
async def delete(curriculum_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM curriculum
        WHERE curriculum_id = $1
        """,
        curriculum_id,
    )
    return RedirectResponse(url="/curriculum/", status_code=303)

@router.get("/{curriculum_id}/subjects")
async def list_subjects(request: Request, curriculum_id: int, conn=Depends(get_conn)):
    curriculum = await conn.fetchrow(
        """
        SELECT *
        FROM curriculum
        WHERE curriculum_id = $1
        """,
        curriculum_id,
    )
    subjects = await conn.fetch(
        """
        SELECT *
        FROM curriculum_subject
        WHERE curriculum_id = $1
        ORDER BY name
        """,
        curriculum_id,
    )
    return templates.TemplateResponse(
        "curriculum/subjects.html",
        {"request": request, "curriculum": curriculum, "subjects": subjects},
    )

# Query 14: Выборка дисциплин учебного плана для семестра
@router.get("/{curriculum_id}/subjects/weekly")
async def subjects_weekly(
    request: Request,
    curriculum_id: int,
    conn=Depends(get_conn),
):
    curriculum = await conn.fetchrow(
        """
        SELECT *
        FROM curriculum
        WHERE curriculum_id = $1
        """,
        curriculum_id,
    )
    rows = await conn.fetch(
        """
        SELECT
            cs.subject_id,
            cs.name          AS subject,
            cs.lecture_hours,
            cs.practice_hours,
            cs.lab_hours,
            cs.assessment_type,
            c.weeks,
            ROUND(cs.lecture_hours::NUMERIC  / c.weeks, 2) AS lectures_per_week,
            ROUND(cs.practice_hours::NUMERIC / c.weeks, 2) AS practice_per_week,
            ROUND(cs.lab_hours::NUMERIC      / c.weeks, 2) AS labs_per_week
        FROM curriculum_subject cs
        JOIN curriculum c       ON cs.curriculum_id = c.curriculum_id
        WHERE c.curriculum_id = $1
        ORDER BY cs.name
        """,
        curriculum_id,
    )
    return templates.TemplateResponse(
        "curriculum/subjects_weekly.html",
        {"request": request, "curriculum": curriculum, "rows": rows},
    )


@router.get("/{curriculum_id}/subjects/add")
async def add_subject_form(request: Request, curriculum_id: int, conn=Depends(get_conn)):
    curriculum = await conn.fetchrow(
        """
        SELECT *
        FROM curriculum
        WHERE curriculum_id = $1
        """,
        curriculum_id,
    )
    return templates.TemplateResponse(
        "curriculum/subject_form.html",
        {"request": request, "curriculum": curriculum, "subject": None},
    )


@router.post("/{curriculum_id}/subjects/add")
async def add_subject_submit(
    curriculum_id: int,
    name: str = Form(...),
    lecture_hours: int = Form(0),
    practice_hours: int = Form(0),
    lab_hours: int = Form(0),
    assessment_type: str = Form(...),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO curriculum_subject
            (curriculum_id, name, lecture_hours, practice_hours, lab_hours, assessment_type)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        curriculum_id, name, lecture_hours, practice_hours, lab_hours, assessment_type,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/subjects", status_code=303
    )


@router.get("/{curriculum_id}/subjects/edit/{subject_id}")
async def edit_subject_form(
    request: Request,
    curriculum_id: int,
    subject_id: int,
    conn=Depends(get_conn),
):
    curriculum = await conn.fetchrow(
        """
        SELECT *
        FROM curriculum
        WHERE curriculum_id = $1
        """,
        curriculum_id,
    )
    subject = await conn.fetchrow(
        """
        SELECT *
        FROM curriculum_subject
        WHERE subject_id = $1
        """,
        subject_id,
    )
    return templates.TemplateResponse(
        "curriculum/subject_form.html",
        {"request": request, "curriculum": curriculum, "subject": subject},
    )


@router.post("/{curriculum_id}/subjects/edit/{subject_id}")
async def edit_subject_submit(
    curriculum_id: int,
    subject_id: int,
    name: str = Form(...),
    lecture_hours: int = Form(0),
    practice_hours: int = Form(0),
    lab_hours: int = Form(0),
    assessment_type: str = Form(...),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE curriculum_subject
           SET name           = $1,
               lecture_hours  = $2,
               practice_hours = $3,
               lab_hours      = $4,
               assessment_type = $5
         WHERE subject_id     = $6
        """,
        name, lecture_hours, practice_hours, lab_hours, assessment_type, subject_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/subjects", status_code=303
    )


@router.post("/{curriculum_id}/subjects/delete/{subject_id}")
async def delete_subject(curriculum_id: int, subject_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM curriculum_subject
        WHERE subject_id = $1
        """,
        subject_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/subjects", status_code=303
    )
