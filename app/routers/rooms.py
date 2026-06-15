from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import asyncpg
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def list_rooms(request: Request, conn=Depends(get_conn)):
    buildings = await conn.fetch(
        """
        SELECT b.*, COUNT(r.room_id) AS room_count
        FROM building b
        LEFT JOIN room r ON r.building_id = b.building_id
        GROUP BY b.building_id
        ORDER BY b.name
        """
    )
    rooms = await conn.fetch(
        """
        SELECT r.*, b.name AS building_name
        FROM room r
        JOIN building b ON r.building_id = b.building_id
        ORDER BY b.name, r.name
        """
    )
    return templates.TemplateResponse(
        "rooms/list.html",
        {"request": request, "buildings": buildings, "rooms": rooms},
    )


@router.get("/buildings/add")
async def add_building_form(request: Request):
    return templates.TemplateResponse(
        "rooms/building_form.html",
        {"request": request, "building": None},
    )


@router.post("/buildings/add")
async def add_building_submit(
    name: str = Form(...),
    address: str = Form(""),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO building (name, address)
        VALUES ($1, $2)
        """,
        name, address,
    )
    return RedirectResponse(url="/rooms/", status_code=303)


@router.get("/buildings/edit/{building_id}")
async def edit_building_form(request: Request, building_id: int, conn=Depends(get_conn)):
    building = await conn.fetchrow(
        """
        SELECT *
        FROM building
        WHERE building_id = $1
        """,
        building_id,
    )
    return templates.TemplateResponse(
        "rooms/building_form.html",
        {"request": request, "building": building},
    )


@router.post("/buildings/edit/{building_id}")
async def edit_building_submit(
    building_id: int,
    name: str = Form(...),
    address: str = Form(""),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE building
           SET name = $1, address = $2
         WHERE building_id = $3
        """,
        name, address, building_id,
    )
    return RedirectResponse(url="/rooms/", status_code=303)


@router.post("/buildings/delete/{building_id}")
async def delete_building(building_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM building
        WHERE building_id = $1
        """,
        building_id,
    )
    return RedirectResponse(url="/rooms/", status_code=303)


# Rooms
@router.get("/rooms/add")
async def add_room_form(request: Request, conn=Depends(get_conn)):
    buildings = await conn.fetch(
        """
        SELECT building_id, name
        FROM building
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "rooms/room_form.html",
        {"request": request, "room": None, "buildings": buildings},
    )


@router.post("/rooms/add")
async def add_room_submit(
    name: str = Form(...),
    building_id: int = Form(...),
    room_type: str = Form(...),
    capacity: int = Form(...),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        INSERT INTO room (name, building_id, room_type, capacity)
        VALUES ($1, $2, $3, $4)
        """,
        name, building_id, room_type, capacity,
    )
    return RedirectResponse(url="/rooms/", status_code=303)


@router.get("/rooms/edit/{room_id}")
async def edit_room_form(request: Request, room_id: int, conn=Depends(get_conn)):
    room = await conn.fetchrow(
        """
        SELECT *
        FROM room
        WHERE room_id = $1
        """,
        room_id,
    )
    buildings = await conn.fetch(
        """
        SELECT building_id, name
        FROM building
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "rooms/room_form.html",
        {"request": request, "room": room, "buildings": buildings},
    )


@router.post("/rooms/edit/{room_id}")
async def edit_room_submit(
    room_id: int,
    name: str = Form(...),
    building_id: int = Form(...),
    room_type: str = Form(...),
    capacity: int = Form(...),
    conn=Depends(get_conn),
):
    await conn.execute(
        """
        UPDATE room
           SET name        = $1,
               building_id = $2,
               room_type   = $3,
               capacity    = $4
         WHERE room_id     = $5
        """,
        name, building_id, room_type, capacity, room_id,
    )
    return RedirectResponse(url="/rooms/", status_code=303)


@router.post("/rooms/delete/{room_id}")
async def delete_room(room_id: int, conn=Depends(get_conn)):
    await conn.execute(
        """
        DELETE FROM room
        WHERE room_id = $1
        """,
        room_id,
    )
    return RedirectResponse(url="/rooms/", status_code=303)
