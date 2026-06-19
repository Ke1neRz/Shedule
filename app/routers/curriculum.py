from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import require_teacher
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


# ===================== CURRICULUM (общий учебный план) =====================

@router.get("/")
async def list_curriculum(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT c.*,
               COUNT(cs.semester_id) AS semesters_count
          FROM curriculum c
          LEFT JOIN curriculum_semester cs ON cs.curriculum_id = c.curriculum_id
         GROUP BY c.curriculum_id
         ORDER BY c.admission_year DESC, c.direction_code, c.name
        """
    )
    return templates.TemplateResponse(
        "curriculum/list.html",
        {"request": request, "curricula": rows},
    )


@router.get("/add")
async def add_form(request: Request, user=Depends(require_teacher)):
    return templates.TemplateResponse(
        "curriculum/form.html",
        {"request": request, "curriculum": None},
    )


@router.post("/add")
async def add_submit(
    name: str = Form(...),
    direction_code: str = Form(""),
    admission_year: int = Form(...),
    duration_years: int = Form(4),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO curriculum (name, direction_code, admission_year, duration_years)
        VALUES ($1, $2, $3, $4)
        """,
        name, direction_code, admission_year, duration_years,
    )
    return RedirectResponse(url="/curriculum/", status_code=303)


@router.get("/edit/{curriculum_id}")
async def edit_form(
    request: Request,
    curriculum_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    row = await conn.fetchrow(
        "SELECT * FROM curriculum WHERE curriculum_id = $1",
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
    admission_year: int = Form(...),
    duration_years: int = Form(4),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE curriculum
           SET name           = $1,
               direction_code = $2,
               admission_year = $3,
               duration_years = $4
         WHERE curriculum_id  = $5
        """,
        name, direction_code, admission_year, duration_years, curriculum_id,
    )
    return RedirectResponse(url="/curriculum/", status_code=303)


@router.post("/delete/{curriculum_id}")
async def delete_curriculum(
    curriculum_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        "DELETE FROM curriculum WHERE curriculum_id = $1",
        curriculum_id,
    )
    return RedirectResponse(url="/curriculum/", status_code=303)


# ===================== SEMESTERS (семестры плана) =====================

async def _get_curriculum_or_404(conn, curriculum_id):
    row = await conn.fetchrow(
        "SELECT * FROM curriculum WHERE curriculum_id = $1", curriculum_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Учебный план не найден")
    return row


@router.get("/{curriculum_id}/semesters")
async def list_semesters(request: Request, curriculum_id: int, conn=Depends(get_conn)):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semesters = await conn.fetch(
        """
        SELECT cs.*,
               COUNT(subj.subject_id) AS subjects_count
          FROM curriculum_semester cs
          LEFT JOIN curriculum_subject subj ON subj.semester_id = cs.semester_id
         WHERE cs.curriculum_id = $1
         GROUP BY cs.semester_id
         ORDER BY cs.semester_number
        """,
        curriculum_id,
    )
    return templates.TemplateResponse(
        "curriculum/semesters.html",
        {"request": request, "curriculum": curriculum, "semesters": semesters},
    )


@router.get("/{curriculum_id}/semesters/add")
async def add_semester_form(
    request: Request,
    curriculum_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    return templates.TemplateResponse(
        "curriculum/semester_form.html",
        {"request": request, "curriculum": curriculum, "semester": None},
    )


@router.post("/{curriculum_id}/semesters/add")
async def add_semester_submit(
    curriculum_id: int,
    semester_number: int = Form(...),
    academic_year: int = Form(...),
    weeks: int = Form(18),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO curriculum_semester (curriculum_id, semester_number, academic_year, weeks)
        VALUES ($1, $2, $3, $4)
        """,
        curriculum_id, semester_number, academic_year, weeks,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters", status_code=303
    )


@router.get("/{curriculum_id}/semesters/{semester_id}/edit")
async def edit_semester_form(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await conn.fetchrow(
        "SELECT * FROM curriculum_semester WHERE semester_id = $1", semester_id,
    )
    return templates.TemplateResponse(
        "curriculum/semester_form.html",
        {"request": request, "curriculum": curriculum, "semester": semester},
    )


@router.post("/{curriculum_id}/semesters/{semester_id}/edit")
async def edit_semester_submit(
    curriculum_id: int,
    semester_id: int,
    semester_number: int = Form(...),
    academic_year: int = Form(...),
    weeks: int = Form(18),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE curriculum_semester
           SET semester_number = $1,
               academic_year   = $2,
               weeks           = $3
         WHERE semester_id     = $4
        """,
        semester_number, academic_year, weeks, semester_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters", status_code=303
    )


@router.post("/{curriculum_id}/semesters/{semester_id}/delete")
async def delete_semester(
    curriculum_id: int,
    semester_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        "DELETE FROM curriculum_semester WHERE semester_id = $1", semester_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters", status_code=303
    )


# ===================== SUBJECTS (дисциплины семестра) =====================

async def _get_semester_or_404(conn, semester_id):
    row = await conn.fetchrow(
        "SELECT * FROM curriculum_semester WHERE semester_id = $1", semester_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Семестр не найден")
    return row


@router.get("/{curriculum_id}/semesters/{semester_id}/subjects")
async def list_subjects(
    request: Request, curriculum_id: int, semester_id: int, conn=Depends(get_conn),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    subjects = await conn.fetch(
        "SELECT * FROM curriculum_subject WHERE semester_id = $1 ORDER BY name",
        semester_id,
    )
    return templates.TemplateResponse(
        "curriculum/subjects.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "subjects": subjects,
        },
    )


@router.get("/{curriculum_id}/semesters/{semester_id}/subjects/weekly")
async def subjects_weekly(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    conn=Depends(get_conn),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    rows = await conn.fetch(
        """
        SELECT
            cs.subject_id,
            cs.name          AS subject,
            cs.lecture_hours,
            cs.practice_hours,
            cs.lab_hours,
            cs.assessment_type,
            sm.weeks,
            ROUND(cs.lecture_hours::NUMERIC  / sm.weeks, 2) AS lectures_per_week,
            ROUND(cs.practice_hours::NUMERIC / sm.weeks, 2) AS practice_per_week,
            ROUND(cs.lab_hours::NUMERIC      / sm.weeks, 2) AS labs_per_week
        FROM curriculum_subject cs
        JOIN curriculum_semester sm ON cs.semester_id = sm.semester_id
        WHERE sm.semester_id = $1
        ORDER BY cs.name
        """,
        semester_id,
    )
    return templates.TemplateResponse(
        "curriculum/subjects_weekly.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "rows": rows,
        },
    )


@router.get("/{curriculum_id}/semesters/{semester_id}/subjects/add")
async def add_subject_form(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    return templates.TemplateResponse(
        "curriculum/subject_form.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "subject": None,
        },
    )


@router.post("/{curriculum_id}/semesters/{semester_id}/subjects/add")
async def add_subject_submit(
    curriculum_id: int,
    semester_id: int,
    name: str = Form(...),
    lecture_hours: int = Form(0),
    practice_hours: int = Form(0),
    lab_hours: int = Form(0),
    assessment_type: str = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO curriculum_subject
            (semester_id, name, lecture_hours, practice_hours, lab_hours, assessment_type)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        semester_id, name, lecture_hours, practice_hours, lab_hours, assessment_type,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters/{semester_id}/subjects",
        status_code=303,
    )


@router.get("/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/edit")
async def edit_subject_form(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    subject = await conn.fetchrow(
        "SELECT * FROM curriculum_subject WHERE subject_id = $1", subject_id,
    )
    return templates.TemplateResponse(
        "curriculum/subject_form.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "subject": subject,
        },
    )


@router.post("/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/edit")
async def edit_subject_submit(
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    name: str = Form(...),
    lecture_hours: int = Form(0),
    practice_hours: int = Form(0),
    lab_hours: int = Form(0),
    assessment_type: str = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE curriculum_subject
           SET name            = $1,
               lecture_hours   = $2,
               practice_hours  = $3,
               lab_hours       = $4,
               assessment_type = $5
         WHERE subject_id      = $6
        """,
        name, lecture_hours, practice_hours, lab_hours, assessment_type, subject_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters/{semester_id}/subjects",
        status_code=303,
    )


@router.post("/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/delete")
async def delete_subject(
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        "DELETE FROM curriculum_subject WHERE subject_id = $1", subject_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters/{semester_id}/subjects",
        status_code=303,
    )


# ===================== LESSONS (занятия дисциплины) =====================

@router.get(
    "/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons"
)
async def list_lessons(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    conn=Depends(get_conn),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    subject = await conn.fetchrow(
        "SELECT * FROM curriculum_subject WHERE subject_id = $1", subject_id,
    )
    lessons = await conn.fetch(
        "SELECT * FROM lesson WHERE subject_id = $1 ORDER BY lesson_type",
        subject_id,
    )
    return templates.TemplateResponse(
        "curriculum/lessons_list.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "subject": subject,
            "lessons": lessons,
        },
    )


@router.get(
    "/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons/add"
)
async def add_lesson_form(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    subject = await conn.fetchrow(
        "SELECT * FROM curriculum_subject WHERE subject_id = $1", subject_id,
    )
    return templates.TemplateResponse(
        "curriculum/lesson_form.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "subject": subject,
            "lesson": None,
        },
    )


@router.post(
    "/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons/add"
)
async def add_lesson_submit(
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    lesson_type: str = Form(...),
    duration_minutes: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO lesson (subject_id, lesson_type, duration_minutes)
        VALUES ($1, $2, $3)
        """,
        subject_id, lesson_type, duration_minutes,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons",
        status_code=303,
    )


@router.get(
    "/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons/{lesson_id}/edit"
)
async def edit_lesson_form(
    request: Request,
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    lesson_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curriculum = await _get_curriculum_or_404(conn, curriculum_id)
    semester = await _get_semester_or_404(conn, semester_id)
    subject = await conn.fetchrow(
        "SELECT * FROM curriculum_subject WHERE subject_id = $1", subject_id,
    )
    lesson = await conn.fetchrow(
        "SELECT * FROM lesson WHERE lesson_id = $1", lesson_id,
    )
    return templates.TemplateResponse(
        "curriculum/lesson_form.html",
        {
            "request": request,
            "curriculum": curriculum,
            "semester": semester,
            "subject": subject,
            "lesson": lesson,
        },
    )


@router.post(
    "/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons/{lesson_id}/edit"
)
async def edit_lesson_submit(
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    lesson_id: int,
    lesson_type: str = Form(...),
    duration_minutes: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE lesson
           SET lesson_type      = $1,
               duration_minutes = $2
         WHERE lesson_id        = $3
        """,
        lesson_type, duration_minutes, lesson_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons",
        status_code=303,
    )


@router.post(
    "/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons/{lesson_id}/delete"
)
async def delete_lesson(
    curriculum_id: int,
    semester_id: int,
    subject_id: int,
    lesson_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        "DELETE FROM lesson WHERE lesson_id = $1", lesson_id,
    )
    return RedirectResponse(
        url=f"/curriculum/{curriculum_id}/semesters/{semester_id}/subjects/{subject_id}/lessons",
        status_code=303,
    )
