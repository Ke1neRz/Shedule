from fastapi import APIRouter, Request, Form, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import asyncpg
from datetime import date, timedelta
from urllib.parse import quote
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def check_teacher_preference_warning(conn, teacher_id, timeslot_id):
    ts = await conn.fetchrow(
        """
        SELECT day_of_week, pair_number
        FROM timeslot
        WHERE timeslot_id = $1
        """,
        timeslot_id,
    )
    if not ts:
        return None

    pref = await conn.fetchrow(
        """
        SELECT is_preferred
        FROM teacher_preference
        WHERE teacher_id = $1
          AND day_of_week = $2
          AND pair_number = $3
        """,
        teacher_id, ts["day_of_week"], ts["pair_number"],
    )
    if pref and not pref["is_preferred"]:
        return (
            "Предупреждение: выбранная пара не является предпочтительной "
            "для преподавателя (для него указано, что он НЕ хочет работать в этот слот)."
        )
    return None


async def validate_schedule_entry(conn, data, exclude_id=None):
    group_id = data["group_id"]
    lesson_id = data["lesson_id"]
    timeslot_id = data["timeslot_id"]
    teacher_id = data["teacher_id"]
    room_id = data.get("room_id")
    entry_date = data["entry_date"]
    week_parity = data.get("week_parity", "all")
    is_online = data.get("is_online", False)

    # 1. Рабочий день
    cal = await conn.fetchrow(
        """
        SELECT is_working
        FROM work_calendar
        WHERE calendar_date = $1
        """,
        entry_date,
    )
    if not cal or not cal["is_working"]:
        raise ValueError("Выбранная дата не является рабочим днём (праздник или выходной).")

    # 2. Чётность недели (ISO week number)
    if week_parity != "all":
        week_num = entry_date.isocalendar()[1]
        is_even = week_num % 2 == 0
        if (week_parity == "even" and not is_even) or (week_parity == "odd" and is_even):
            raise ValueError(
                "Номер недели не соответствует выбранной чётности (чётная/нечётная)."
            )

    # 3. Получаем данные занятия и группы
    lesson = await conn.fetchrow(
        """
        SELECT lesson_type, duration_minutes
        FROM lesson
        WHERE lesson_id = $1
        """,
        lesson_id,
    )
    group = await conn.fetchrow(
        """
        SELECT student_count
        FROM study_group
        WHERE group_id = $1
        """,
        group_id,
    )
    if not lesson or not group:
        raise ValueError("Неверные данные занятия или группы.")
    lesson_type = lesson["lesson_type"]
    student_count = group["student_count"]

    # 4. Преподаватель должен быть связан с занятием
    teacher_link = await conn.fetchrow(
        """
        SELECT 1
        FROM teacher_lesson
        WHERE teacher_id = $1
          AND lesson_id = $2
        """,
        teacher_id, lesson_id,
    )
    if not teacher_link:
        raise ValueError("Выбранный преподаватель не назначен на это учебное занятие.")

    # 5. Лаборатория только в lab/computer, вместимость
    if not is_online and room_id:
        room = await conn.fetchrow(
            """
            SELECT room_type, capacity, building_id
            FROM room
            WHERE room_id = $1
            """,
            room_id,
        )
        if not room:
            raise ValueError("Аудитория не найдена.")
        if lesson_type == "lab" and room["room_type"] not in ("lab", "computer"):
            raise ValueError(
                "Лабораторные занятия могут проводиться только в лаборатории или компьютерном классе."
            )
        if room["capacity"] < student_count:
            raise ValueError(
                f"Вместимость аудитории ({room['capacity']}) меньше количества студентов ({student_count})."
            )
    elif lesson_type == "lab" and not is_online:
        raise ValueError(
            "Для лабораторного занятия необходимо выбрать аудиторию типа 'лаборатория' или 'компьютерный класс'."
        )

    # 6. Не более 5 пар в день (группа, преподаватель)
    for check_id, check_name in [(group_id, "группа"), (teacher_id, "преподаватель")]:
        field = "group_id" if check_name == "группа" else "teacher_id"
        count = await conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM schedule_entry
            WHERE {field} = $1
              AND entry_date = $2
              AND entry_id <> COALESCE($3, 0)
            """,
            check_id, entry_date, exclude_id,
        )
        if count >= 5:
            raise ValueError(f"{check_name.capitalize()} уже имеет 5 пар в этот день.")

    # 7. Пересечения по времени
    overlap = await conn.fetchrow(
        """
        SELECT 1
        FROM schedule_entry
        WHERE group_id = $1
          AND timeslot_id = $2
          AND entry_date = $3
          AND entry_id <> COALESCE($4, 0)
        """,
        group_id, timeslot_id, entry_date, exclude_id,
    )
    if overlap:
        raise ValueError("У группы уже есть занятие в это время.")

    overlap = await conn.fetchrow(
        """
        SELECT 1
        FROM schedule_entry
        WHERE teacher_id = $1
          AND timeslot_id = $2
          AND entry_date = $3
          AND entry_id <> COALESCE($4, 0)
        """,
        teacher_id, timeslot_id, entry_date, exclude_id,
    )
    if overlap:
        raise ValueError("Преподаватель уже занят в это время.")

    if not is_online and room_id:
        overlap = await conn.fetchrow(
            """
            SELECT 1
            FROM schedule_entry
            WHERE room_id = $1
              AND timeslot_id = $2
              AND entry_date = $3
              AND entry_id <> COALESCE($4, 0)
            """,
            room_id, timeslot_id, entry_date, exclude_id,
        )
        if overlap:
            raise ValueError("Аудитория уже занята в это время.")

    # 8. Перемещение между корпусами и gap <= 90 мин (только для соседних пар)
    current = await conn.fetchrow(
        """
        SELECT pair_number, start_time, end_time
        FROM timeslot
        WHERE timeslot_id = $1
        """,
        timeslot_id,
    )
    cur_pair = current["pair_number"]
    cur_start = current["start_time"]
    cur_end = current["end_time"]
    cur_start_min = cur_start.hour * 60 + cur_start.minute
    cur_end_min = cur_end.hour * 60 + cur_end.minute

    for field_name, field_val in [("group_id", group_id), ("teacher_id", teacher_id)]:
        label = "группы" if field_name == "group_id" else "преподавателя"
        # Собираем все занятия в день + текущее
        rows = await conn.fetch(
            f"""
            SELECT se.room_id, t.pair_number, t.start_time, t.end_time
            FROM schedule_entry se
            JOIN timeslot t ON se.timeslot_id = t.timeslot_id
            WHERE se.{field_name} = $1
              AND se.entry_date = $2
              AND se.entry_id <> COALESCE($3, 0)
            ORDER BY t.pair_number
            """,
            field_val, entry_date, exclude_id,
        )
        pairs = []
        for r in rows:
            pairs.append(
                {
                    "pair_number": r["pair_number"],
                    "start_min": r["start_time"].hour * 60 + r["start_time"].minute,
                    "end_min": r["end_time"].hour * 60 + r["end_time"].minute,
                    "room_id": r["room_id"],
                }
            )
        # добавляем текущее
        pairs.append(
            {
                "pair_number": cur_pair,
                "start_min": cur_start_min,
                "end_min": cur_end_min,
                "room_id": room_id if not is_online else None,
            }
        )
        pairs.sort(key=lambda x: x["pair_number"])
        # проверяем соседние
        for i in range(1, len(pairs)):
            prev = pairs[i - 1]
            nxt = pairs[i]
            gap = nxt["start_min"] - prev["end_min"]
            if gap > 90:
                raise ValueError(
                    f"У {label} перерыв между {prev['pair_number']}-й и {nxt['pair_number']}-й парой "
                    f"{gap} минут (превышает 90 мин)."
                )
            # соседние пары (diff == 1) -> проверяем перемещение
            if nxt["pair_number"] - prev["pair_number"] == 1:
                if prev["room_id"] and nxt["room_id"] and prev["room_id"] != nxt["room_id"]:
                    b1 = await conn.fetchrow(
                        """
                        SELECT building_id
                        FROM room
                        WHERE room_id = $1
                        """,
                        prev["room_id"],
                    )
                    b2 = await conn.fetchrow(
                        """
                        SELECT building_id
                        FROM room
                        WHERE room_id = $1
                        """,
                        nxt["room_id"],
                    )
                    if b1 and b2 and b1["building_id"] != b2["building_id"]:
                        dist = await conn.fetchrow(
                            """
                            SELECT distance_minutes
                            FROM building_distance
                            WHERE (from_building_id  = $1 AND to_building_id = $2)
                               OR (from_building_id  = $2 AND to_building_id = $1)
                            """,
                            b1["building_id"], b2["building_id"],
                        )
                        distance = dist["distance_minutes"] if dist else 10
                        if gap < distance + 5:
                            raise ValueError(
                                f"Недостаточно времени на перемещение между корпусами ({distance} мин) "
                                f"для {label} между {prev['pair_number']}-й и {nxt['pair_number']}-й парой."
                            )

    return True


@router.get("/")
async def schedule_index(
    request: Request,
    group_id: int = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    warning: str = Query(None),
    conn=Depends(get_conn),
):
    from datetime import datetime

    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    entries = []
    if group_id and date_from and date_to:
        d_from = datetime.fromisoformat(date_from).date()
        d_to = datetime.fromisoformat(date_to).date()
        entries = await conn.fetch(
            """
            SELECT
                t.day_of_week,
                t.pair_number,
                t.start_time,
                t.end_time,
                s.entry_id,
                cs.name            AS subject,
                l.lesson_type,
                tch.last_name || ' ' || LEFT(tch.first_name, 1) || '.'
                    || COALESCE(LEFT(tch.middle_name, 1) || '.', '')
                                   AS teacher_short,
                tch.last_name || ' ' || tch.first_name || ' '
                    || COALESCE(tch.middle_name, '')
                                   AS teacher_full,
                r.name             AS room,
                b.name             AS building,
                s.is_online,
                s.online_link,
                s.week_parity,
                s.entry_date
            FROM schedule_entry s
            JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
            JOIN lesson l           ON s.lesson_id   = l.lesson_id
            JOIN curriculum_subject cs
                                    ON l.subject_id = cs.subject_id
            JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
            LEFT JOIN room r        ON s.room_id     = r.room_id
            LEFT JOIN building b    ON r.building_id = b.building_id
            WHERE s.group_id = $1
              AND s.entry_date BETWEEN $2 AND $3
            ORDER BY t.day_of_week, t.pair_number, s.entry_date
            """,
            group_id, d_from, d_to,
        )

    # Получаем академические группы для выбранной study_group
    academic_groups = []
    if group_id:
        ag = await conn.fetch(
            """
            SELECT ag.group_number
            FROM academic_group ag
            JOIN study_group_academic_group sag
                 ON ag.academic_group_id = sag.academic_group_id
            WHERE sag.study_group_id = $1
            """,
            group_id,
        )
        academic_groups = [r["group_number"] for r in ag]

    # Формируем структуру для таблицы
    table = {d: {p: [] for p in range(1, 9)} for d in range(1, 7)}
    for e in entries:
        table[e["day_of_week"]][e["pair_number"]].append(e)

    return templates.TemplateResponse(
        "schedule/index.html",
        {
            "request": request,
            "groups": groups,
            "group_id": group_id,
            "date_from": date_from,
            "date_to": date_to,
            "academic_groups": academic_groups,
            "table": table,
            "days": {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"},
            "warning": warning,
        },
    )


@router.get("/add")
async def add_form(
    request: Request,
    group_id: int = Query(None),
    date: str = Query(None),
    conn=Depends(get_conn),
):
    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    timeslots = await conn.fetch(
        """
        SELECT timeslot_id, day_of_week, pair_number, start_time, end_time
        FROM timeslot
        ORDER BY day_of_week, pair_number
        """
    )
    teachers = await conn.fetch(
        """
        SELECT teacher_id, last_name || ' ' || first_name AS full_name
        FROM teacher
        ORDER BY last_name
        """
    )
    rooms = await conn.fetch(
        """
        SELECT room_id,
               name || ' (' || room_type || ', ' || capacity || ' чел)' AS label
        FROM room
        ORDER BY name
        """
    )
    lessons = await conn.fetch(
        """
        SELECT l.lesson_id, cs.name AS subject_name, l.lesson_type, l.duration_minutes
        FROM lesson l
        JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
        ORDER BY cs.name, l.lesson_type
        """
    )
    return templates.TemplateResponse(
        "schedule/form.html",
        {
            "request": request,
            "entry": None,
            "groups": groups,
            "timeslots": timeslots,
            "teachers": teachers,
            "rooms": rooms,
            "lessons": lessons,
            "preselected_group": group_id,
            "preselected_date": date,
        },
    )


@router.post("/add")
async def add_submit(
    group_id: int = Form(...),
    lesson_id: int = Form(...),
    timeslot_id: int = Form(...),
    teacher_id: int = Form(...),
    room_id: int = Form(None),
    entry_date: str = Form(...),
    week_parity: str = Form("all"),
    is_online: bool = Form(False),
    online_link: str = Form(""),
    conn=Depends(get_conn),
):
    data = {
        "group_id": group_id,
        "lesson_id": lesson_id,
        "timeslot_id": timeslot_id,
        "teacher_id": teacher_id,
        "room_id": room_id,
        "entry_date": date.fromisoformat(entry_date),
        "week_parity": week_parity,
        "is_online": is_online,
    }
    try:
        await validate_schedule_entry(conn, data)
    except ValueError as e:
        return HTMLResponse(
            f"<h1>Ошибка валидации</h1><p>{e}</p>"
            f"<a href='/schedule/add?group_id={group_id}&date={entry_date}'>Назад</a>",
            status_code=400,
        )
    warning = await check_teacher_preference_warning(conn, teacher_id, timeslot_id)
    await conn.execute(
        """
        INSERT INTO schedule_entry
            (group_id, lesson_id, timeslot_id, teacher_id, room_id,
             entry_date, week_parity, is_online, online_link)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        group_id, lesson_id, timeslot_id, teacher_id, room_id,
        date.fromisoformat(entry_date), week_parity, is_online, online_link,
    )
    url = f"/schedule/?group_id={group_id}&date_from={entry_date}&date_to={entry_date}"
    if warning:
        url += f"&warning={quote(warning)}"
    return RedirectResponse(url=url, status_code=303)


@router.get("/edit/{entry_id}")
async def edit_form(request: Request, entry_id: int, conn=Depends(get_conn)):
    entry = await conn.fetchrow(
        """
        SELECT *
        FROM schedule_entry
        WHERE entry_id = $1
        """,
        entry_id,
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    timeslots = await conn.fetch(
        """
        SELECT timeslot_id, day_of_week, pair_number, start_time, end_time
        FROM timeslot
        ORDER BY day_of_week, pair_number
        """
    )
    teachers = await conn.fetch(
        """
        SELECT teacher_id, last_name || ' ' || first_name AS full_name
        FROM teacher
        ORDER BY last_name
        """
    )
    rooms = await conn.fetch(
        """
        SELECT room_id,
               name || ' (' || room_type || ', ' || capacity || ' чел)' AS label
        FROM room
        ORDER BY name
        """
    )
    lessons = await conn.fetch(
        """
        SELECT l.lesson_id, cs.name AS subject_name, l.lesson_type, l.duration_minutes
        FROM lesson l
        JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
        ORDER BY cs.name, l.lesson_type
        """
    )
    return templates.TemplateResponse(
        "schedule/form.html",
        {
            "request": request,
            "entry": entry,
            "groups": groups,
            "timeslots": timeslots,
            "teachers": teachers,
            "rooms": rooms,
            "lessons": lessons,
            "preselected_group": None,
            "preselected_date": None,
        },
    )


@router.post("/edit/{entry_id}")
async def edit_submit(
    entry_id: int,
    group_id: int = Form(...),
    lesson_id: int = Form(...),
    timeslot_id: int = Form(...),
    teacher_id: int = Form(...),
    room_id: int = Form(None),
    entry_date: str = Form(...),
    week_parity: str = Form("all"),
    is_online: bool = Form(False),
    online_link: str = Form(""),
    conn=Depends(get_conn),
):
    data = {
        "group_id": group_id,
        "lesson_id": lesson_id,
        "timeslot_id": timeslot_id,
        "teacher_id": teacher_id,
        "room_id": room_id,
        "entry_date": date.fromisoformat(entry_date),
        "week_parity": week_parity,
        "is_online": is_online,
    }
    try:
        await validate_schedule_entry(conn, data, exclude_id=entry_id)
    except ValueError as e:
        return HTMLResponse(
            f"<h1>Ошибка валидации</h1><p>{e}</p>"
            f"<a href='/schedule/edit/{entry_id}'>Назад</a>",
            status_code=400,
        )
    warning = await check_teacher_preference_warning(conn, teacher_id, timeslot_id)
    await conn.execute(
        """
        UPDATE schedule_entry
           SET group_id    = $1,
               lesson_id   = $2,
               timeslot_id = $3,
               teacher_id  = $4,
               room_id     = $5,
               entry_date  = $6,
               week_parity = $7,
               is_online   = $8,
               online_link = $9
         WHERE entry_id    = $10
        """,
        group_id, lesson_id, timeslot_id, teacher_id, room_id,
        date.fromisoformat(entry_date), week_parity, is_online, online_link,
        entry_id,
    )
    url = f"/schedule/?group_id={group_id}&date_from={entry_date}&date_to={entry_date}"
    if warning:
        url += f"&warning={quote(warning)}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/delete/{entry_id}")
async def delete_entry(entry_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT group_id, entry_date
        FROM schedule_entry
        WHERE entry_id = $1
        """,
        entry_id,
    )
    await conn.execute(
        """
        DELETE FROM schedule_entry
        WHERE entry_id = $1
        """,
        entry_id,
    )
    if row:
        return RedirectResponse(
            url=f"/schedule/?group_id={row['group_id']}&date_from={row['entry_date']}&date_to={row['entry_date']}",
            status_code=303,
        )
    return RedirectResponse(url="/schedule/", status_code=303)


# Query 11: Копирование расписания
@router.get("/copy")
async def copy_form(request: Request, conn=Depends(get_conn)):
    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "schedule/copy.html",
        {"request": request, "groups": groups},
    )


@router.post("/copy")
async def copy_submit(
    group_id: int = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    offset_weeks: int = Form(...),
    conn=Depends(get_conn),
):
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    try:
        await conn.execute(
            """
            INSERT INTO schedule_entry
                (group_id, lesson_id, timeslot_id, teacher_id, room_id,
                 entry_date, week_parity, is_online, online_link)
            SELECT group_id, lesson_id, timeslot_id, teacher_id, room_id,
                   entry_date + ($3 || ' weeks')::INTERVAL,
                   week_parity, is_online, online_link
            FROM schedule_entry
            WHERE group_id = $1
              AND entry_date BETWEEN $2 AND $4
            """,
            group_id, d_from, str(offset_weeks), d_to,
        )
    except asyncpg.exceptions.UniqueViolationError:
        return HTMLResponse(
            "<h1>Ошибка копирования</h1>"
            "<p>Некоторые записи пересекаются с существующим расписанием.</p>",
            status_code=400,
        )
    new_from = (d_from + timedelta(weeks=offset_weeks)).isoformat()
    new_to = (d_to + timedelta(weeks=offset_weeks)).isoformat()
    return RedirectResponse(
        url=f"/schedule/?group_id={group_id}&date_from={new_from}&date_to={new_to}",
        status_code=303,
    )
