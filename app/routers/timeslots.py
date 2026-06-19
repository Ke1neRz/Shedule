from fastapi import APIRouter, Depends, Request

from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


@router.get("/")
async def list_timeslots(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT *
        FROM timeslot
        ORDER BY day_of_week, pair_number
        """
    )
    return templates.TemplateResponse(
        "timeslots/list.html",
        {"request": request, "timeslots": rows},
    )
