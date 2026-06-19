from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
import asyncpg

from app.auth import require_teacher
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


@router.get("/")
async def list_groups(request: Request, conn=Depends(get_conn)):
    academic = await conn.fetch(
        """
        SELECT ag.*, c.name AS curriculum_name
        FROM academic_group ag
        JOIN curriculum c ON ag.curriculum_id = c.curriculum_id
        ORDER BY ag.group_number
        """
    )
    study = await conn.fetch(
        """
        SELECT sg.*,
               c.name AS curriculum_name,
               sm.semester_number,
               sm.academic_year,
               STRING_AGG(ag.group_number, ', ' ORDER BY ag.group_number)
                   AS academic_groups
          FROM study_group sg
          JOIN curriculum_semester sm ON sg.semester_id  = sm.semester_id
          JOIN curriculum c          ON sm.curriculum_id = c.curriculum_id
          LEFT JOIN study_group_academic_group sag
                    ON sag.study_group_id = sg.group_id
          LEFT JOIN academic_group ag
                    ON sag.academic_group_id = ag.academic_group_id
         GROUP BY sg.group_id, c.name, sm.semester_number, sm.academic_year
         ORDER BY sg.name
        """
    )
    return templates.TemplateResponse(
        "groups/list.html",
        {"request": request, "academic": academic, "study": study},
    )


@router.get("/academic/add")
async def add_academic_form(
    request: Request,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    curricula = await conn.fetch(
        """
        SELECT curriculum_id, name
        FROM curriculum
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "groups/academic_form.html",
        {"request": request, "group": None, "curricula": curricula},
    )


@router.post("/academic/add")
async def add_academic_submit(
    group_number: str = Form(...),
    curriculum_id: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO academic_group (group_number, curriculum_id)
        VALUES ($1, $2)
        """,
        group_number, curriculum_id,
    )
    return RedirectResponse(url="/groups/", status_code=303)


@router.get("/academic/edit/{academic_group_id}")
async def edit_academic_form(
    request: Request,
    academic_group_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    group = await conn.fetchrow(
        """
        SELECT *
        FROM academic_group
        WHERE academic_group_id = $1
        """,
        academic_group_id,
    )
    curricula = await conn.fetch(
        """
        SELECT curriculum_id, name
        FROM curriculum
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "groups/academic_form.html",
        {"request": request, "group": group, "curricula": curricula},
    )


@router.post("/academic/edit/{academic_group_id}")
async def edit_academic_submit(
    academic_group_id: int,
    group_number: str = Form(...),
    curriculum_id: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE academic_group
           SET group_number   = $1,
               curriculum_id = $2
         WHERE academic_group_id = $3
        """,
        group_number, curriculum_id, academic_group_id,
    )
    return RedirectResponse(url="/groups/", status_code=303)


@router.post("/academic/delete/{academic_group_id}")
async def delete_academic(
    academic_group_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        DELETE FROM academic_group
        WHERE academic_group_id = $1
        """,
        academic_group_id,
    )
    return RedirectResponse(url="/groups/", status_code=303)


# ===================== STUDY GROUPS (учебные группы) =====================

async def _fetch_semesters(conn):
    return await conn.fetch(
        """
        SELECT sm.semester_id,
               sm.semester_number,
               sm.academic_year,
               c.name AS curriculum_name,
               c.direction_code,
               c.curriculum_id,
               (c.name || ' / ' || sm.semester_number || '-й семестр / ' || sm.academic_year)
                   AS label
          FROM curriculum_semester sm
          JOIN curriculum c ON sm.curriculum_id = c.curriculum_id
         ORDER BY c.admission_year DESC, sm.semester_number
        """
    )


@router.get("/study/add")
async def add_study_form(
    request: Request,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    semesters = await _fetch_semesters(conn)
    academic = await conn.fetch(
        """
        SELECT ag.academic_group_id,
               ag.group_number,
               c.name AS curriculum_name
          FROM academic_group ag
          JOIN curriculum c ON ag.curriculum_id = c.curriculum_id
         ORDER BY ag.group_number
        """
    )
    return templates.TemplateResponse(
        "groups/study_form.html",
        {"request": request, "group": None, "semesters": semesters, "academic": academic},
    )


@router.post("/study/add")
async def add_study_submit(
    name: str = Form(...),
    student_count: int = Form(...),
    semester_id: int = Form(...),
    academic_group_ids: list[int] = Form([]),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    row = await conn.fetchrow(
        """
        INSERT INTO study_group (name, student_count, semester_id)
        VALUES ($1, $2, $3)
        RETURNING group_id
        """,
        name, student_count, semester_id,
    )
    for ag_id in academic_group_ids:
        await conn.execute(
            """
            INSERT INTO study_group_academic_group
                (study_group_id, academic_group_id)
            VALUES ($1, $2)
            """,
            row["group_id"], ag_id,
        )
    return RedirectResponse(url="/groups/", status_code=303)


@router.get("/study/edit/{group_id}")
async def edit_study_form(
    request: Request,
    group_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    group = await conn.fetchrow(
        """
        SELECT *
        FROM study_group
        WHERE group_id = $1
        """,
        group_id,
    )
    semesters = await _fetch_semesters(conn)
    academic = await conn.fetch(
        """
        SELECT ag.academic_group_id,
               ag.group_number,
               c.name AS curriculum_name
          FROM academic_group ag
          JOIN curriculum c ON ag.curriculum_id = c.curriculum_id
         ORDER BY ag.group_number
        """
    )
    selected = await conn.fetch(
        """
        SELECT academic_group_id
        FROM study_group_academic_group
        WHERE study_group_id = $1
        """,
        group_id,
    )
    selected_ids = [r["academic_group_id"] for r in selected]
    return templates.TemplateResponse(
        "groups/study_form.html",
        {
            "request": request,
            "group": group,
            "semesters": semesters,
            "academic": academic,
            "selected_ids": selected_ids,
        },
    )


@router.post("/study/edit/{group_id}")
async def edit_study_submit(
    group_id: int,
    name: str = Form(...),
    student_count: int = Form(...),
    semester_id: int = Form(...),
    academic_group_ids: list[int] = Form([]),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE study_group
           SET name          = $1,
               student_count = $2,
               semester_id   = $3
         WHERE group_id      = $4
        """,
        name, student_count, semester_id, group_id,
    )
    await conn.execute(
        """
        DELETE FROM study_group_academic_group
        WHERE study_group_id = $1
        """,
        group_id,
    )
    for ag_id in academic_group_ids:
        await conn.execute(
            """
            INSERT INTO study_group_academic_group
                (study_group_id, academic_group_id)
            VALUES ($1, $2)
            """,
            group_id, ag_id,
        )
    return RedirectResponse(url="/groups/", status_code=303)


@router.post("/study/delete/{group_id}")
async def delete_study(
    group_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        DELETE FROM study_group
        WHERE group_id = $1
        """,
        group_id,
    )
    return RedirectResponse(url="/groups/", status_code=303)
