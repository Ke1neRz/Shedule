from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
import asyncpg

from app.auth import require_teacher
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


@router.get("/")
async def list_divisions(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        WITH RECURSIVE tree AS (
            SELECT division_id, name, parent_id, 0 AS level, name::TEXT AS path
            FROM division
            WHERE parent_id IS NULL
            UNION ALL
            SELECT d.division_id, d.name, d.parent_id, t.level + 1,
                   t.path || ' → ' || d.name
            FROM division d
            JOIN tree t ON d.parent_id = t.division_id
        )
        SELECT division_id, name, level, path
        FROM tree
        ORDER BY path
        """
    )
    return templates.TemplateResponse(
        "divisions/list.html",
        {"request": request, "divisions": rows},
    )


@router.get("/add")
async def add_form(
    request: Request,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    parents = await conn.fetch(
        """
        SELECT division_id, name
        FROM division
        ORDER BY name
        """
    )
    universities = await conn.fetch(
        """
        SELECT university_id, name
        FROM university
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "divisions/form.html",
        {
            "request": request,
            "division": None,
            "parents": parents,
            "universities": universities,
        },
    )


@router.post("/add")
async def add_submit(
    name: str = Form(...),
    parent_id: int = Form(None),
    university_id: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO division (name, parent_id, university_id)
        VALUES ($1, $2, $3)
        """,
        name, parent_id, university_id,
    )
    return RedirectResponse(url="/divisions/", status_code=303)


@router.get("/edit/{division_id}")
async def edit_form(
    request: Request,
    division_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    division = await conn.fetchrow(
        """
        SELECT *
        FROM division
        WHERE division_id = $1
        """,
        division_id,
    )
    parents = await conn.fetch(
        """
        SELECT division_id, name
        FROM division
        ORDER BY name
        """
    )
    universities = await conn.fetch(
        """
        SELECT university_id, name
        FROM university
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "divisions/form.html",
        {
            "request": request,
            "division": division,
            "parents": parents,
            "universities": universities,
        },
    )


@router.post("/edit/{division_id}")
async def edit_submit(
    division_id: int,
    name: str = Form(...),
    parent_id: int = Form(None),
    university_id: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE division
           SET name = $1, parent_id = $2, university_id = $3
         WHERE division_id = $4
        """,
        name, parent_id, university_id, division_id,
    )
    return RedirectResponse(url="/divisions/", status_code=303)


@router.post("/delete/{division_id}")
async def delete(
    division_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        DELETE FROM division
        WHERE division_id = $1
        """,
        division_id,
    )
    return RedirectResponse(url="/divisions/", status_code=303)
