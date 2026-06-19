from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import require_teacher
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


@router.get("/")
async def list_universities(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT *
        FROM university
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "universities/list.html",
        {"request": request, "universities": rows},
    )


@router.get("/add")
async def add_form(request: Request, user=Depends(require_teacher)):
    return templates.TemplateResponse(
        "universities/form.html",
        {"request": request, "university": None},
    )


@router.post("/add")
async def add_submit(
    name: str = Form(...),
    address: str = Form(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        INSERT INTO university (name, address)
        VALUES ($1, $2)
        """,
        name, address,
    )
    return RedirectResponse(url="/universities/", status_code=303)


@router.get("/edit/{university_id}")
async def edit_form(
    request: Request,
    university_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    row = await conn.fetchrow(
        """
        SELECT *
        FROM university
        WHERE university_id = $1
        """,
        university_id,
    )
    return templates.TemplateResponse(
        "universities/form.html",
        {"request": request, "university": row},
    )


@router.post("/edit/{university_id}")
async def edit_submit(
    university_id: int,
    name: str = Form(...),
    address: str = Form(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        UPDATE university
           SET name = $1, address = $2
         WHERE university_id = $3
        """,
        name, address, university_id,
    )
    return RedirectResponse(url="/universities/", status_code=303)


@router.post("/delete/{university_id}")
async def delete(
    university_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        """
        DELETE FROM university
        WHERE university_id = $1
        """,
        university_id,
    )
    return RedirectResponse(url="/universities/", status_code=303)
