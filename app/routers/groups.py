from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import asyncpg
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
        SELECT sg.*, c.name AS curriculum_name,
               STRING_AGG(ag.group_number, ', ' ORDER BY ag.group_number)
                   AS academic_groups
        FROM study_group sg
        JOIN curriculum c ON sg.curriculum_id = c.curriculum_id
        LEFT JOIN study_group_academic_group sag
                  ON sag.study_group_id = sg.group_id
        LEFT JOIN academic_group ag
                  ON sag.academic_group_id = ag.academic_group_id
        GROUP BY sg.group_id, c.name
        ORDER BY sg.name
        """
    )
    return templates.TemplateResponse(
        "groups/list.html",
        {"request": request, "academic": academic, "study": study},
    )


@router.get("/academic/add")
async def add_academic_form(request: Request, conn=Depends(get_conn)):
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
    request: Request, academic_group_id: int, conn=Depends(get_conn)
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
async def delete_academic(academic_group_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM academic_group
        WHERE academic_group_id = $1
        """,
        academic_group_id,
    )
    return RedirectResponse(url="/groups/", status_code=303)

# Study groups
@router.get("/study/add")
async def add_study_form(request: Request, conn=Depends(get_conn)):
    curricula = await conn.fetch(
        """
        SELECT curriculum_id, name
        FROM curriculum
        ORDER BY name
        """
    )
    academic = await conn.fetch(
        """
        SELECT academic_group_id, group_number
        FROM academic_group
        ORDER BY group_number
        """
    )
    return templates.TemplateResponse(
        "groups/study_form.html",
        {"request": request, "group": None, "curricula": curricula, "academic": academic},
    )


@router.post("/study/add")
async def add_study_submit(
    name: str = Form(...),
    student_count: int = Form(...),
    curriculum_id: int = Form(...),
    academic_group_ids: list[int] = Form([]),
    conn=Depends(get_conn),
):
    row = await conn.fetchrow(
        """
        INSERT INTO study_group (name, student_count, curriculum_id)
        VALUES ($1, $2, $3)
        RETURNING group_id
        """,
        name, student_count, curriculum_id,
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
async def edit_study_form(request: Request, group_id: int, conn=Depends(get_conn)):
    group = await conn.fetchrow(
        """
        SELECT *
        FROM study_group
        WHERE group_id = $1
        """,
        group_id,
    )
    curricula = await conn.fetch(
        """
        SELECT curriculum_id, name
        FROM curriculum
        ORDER BY name
        """
    )
    academic = await conn.fetch(
        """
        SELECT academic_group_id, group_number
        FROM academic_group
        ORDER BY group_number
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
            "curricula": curricula,
            "academic": academic,
            "selected_ids": selected_ids,
        },
    )


@router.post("/study/edit/{group_id}")
async def edit_study_submit(
    group_id: int,
    name: str = Form(...),
    student_count: int = Form(...),
    curriculum_id: int = Form(...),
    academic_group_ids: list[int] = Form([]),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE study_group
           SET name          = $1,
               student_count = $2,
               curriculum_id = $3
         WHERE group_id      = $4
        """,
        name, student_count, curriculum_id, group_id,
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
async def delete_study(group_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM study_group
        WHERE group_id = $1
        """,
        group_id,
    )
    return RedirectResponse(url="/groups/", status_code=303)
