from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
