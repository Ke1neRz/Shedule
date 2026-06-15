from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import date, datetime
from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Главная страница отчётов
@router.get("/")
async def index(request: Request, conn=Depends(get_conn)):
    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    divisions = await conn.fetch(
        """
        SELECT division_id, name
        FROM division
        ORDER BY name
        """
    )
    return templates.TemplateResponse(
        "reports/index.html",
        {"request": request, "groups": groups, "divisions": divisions},
    )

# Query 1: Расписание одной учебной группы
@router.get("/group")
async def report_group(
    request: Request,
    group_id: int = Query(...),
    date_from: str = Query(...),
    date_to: str = Query(...),
):
    return RedirectResponse(
        url=f"/schedule/?group_id={group_id}&date_from={date_from}&date_to={date_to}"
    )

# Query 2: Шахматная ведомость (расписание нескольких групп)
@router.get("/chess")
async def chess_report(
    request: Request,
    group_ids: list[int] = Query([]),
    date_from: str = Query(...),
    date_to: str = Query(...),
    conn=Depends(get_conn),
):
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)

    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    selected = [g for g in groups if g["group_id"] in group_ids]
    entries = []

    if group_ids:
        entries = await conn.fetch(
            """
            SELECT
                t.day_of_week,
                t.pair_number,
                t.start_time,
                t.end_time,
                sg.name            AS group_name,
                cs.name            AS subject,
                l.lesson_type,
                tch.last_name || ' ' || LEFT(tch.first_name, 1) || '.'
                                   AS teacher_short,
                r.name             AS room,
                s.is_online,
                s.entry_date
            FROM schedule_entry s
            JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
            JOIN study_group sg     ON s.group_id    = sg.group_id
            JOIN lesson l           ON s.lesson_id   = l.lesson_id
            JOIN curriculum_subject cs
                                    ON l.subject_id = cs.subject_id
            JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
            LEFT JOIN room r        ON s.room_id     = r.room_id
            WHERE s.group_id = ANY($1)
              AND s.entry_date BETWEEN $2 AND $3
            ORDER BY t.day_of_week, t.pair_number, sg.name
            """,
            group_ids, d_from, d_to,
        )

    table = {}
    for e in entries:
        key = (e["day_of_week"], e["pair_number"])
        if key not in table:
            table[key] = {}
        table[key][e["group_name"]] = e

    return templates.TemplateResponse(
        "reports/chess.html",
        {
            "request": request,
            "groups": groups,
            "selected_ids": group_ids,
            "selected_groups": selected,
            "date_from": date_from,
            "date_to": date_to,
            "table": table,
            "days": {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"},
        },
    )

# Query 3: Расписание консультаций, зачётов и экзаменов
@router.get("/exams")
async def exams_report(
    request: Request,
    group_ids: list[int] = Query([]),
    date_from: str = Query(...),
    date_to: str = Query(...),
    conn=Depends(get_conn),
):
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)

    groups = await conn.fetch(
        """
        SELECT group_id, name
        FROM study_group
        ORDER BY name
        """
    )
    entries = []

    if group_ids:
        entries = await conn.fetch(
            """
            SELECT
                sg.name            AS group_name,
                cs.name            AS subject,
                l.lesson_type,
                s.entry_date,
                t.start_time,
                t.end_time,
                t.pair_number,
                tch.last_name || ' ' || LEFT(tch.first_name, 1) || '.'
                                   AS teacher_short,
                r.name             AS room,
                b.name             AS building,
                s.is_online
            FROM schedule_entry s
            JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
            JOIN study_group sg     ON s.group_id    = sg.group_id
            JOIN lesson l           ON s.lesson_id   = l.lesson_id
            JOIN curriculum_subject cs
                                    ON l.subject_id = cs.subject_id
            JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
            LEFT JOIN room r        ON s.room_id     = r.room_id
            LEFT JOIN building b    ON r.building_id = b.building_id
            WHERE s.group_id = ANY($1)
              AND s.entry_date BETWEEN $2 AND $3
              AND l.lesson_type IN ('exam', 'pass_test', 'consult')
            ORDER BY s.entry_date, t.start_time
            """,
            group_ids, d_from, d_to,
        )

    return templates.TemplateResponse(
        "reports/exams.html",
        {
            "request": request,
            "groups": groups,
            "selected_ids": group_ids,
            "date_from": date_from,
            "date_to": date_to,
            "entries": entries,
        },
    )

# Query 4: План занятости преподавателей одного подразделения
@router.get("/teachers")
async def teachers_report(
    request: Request,
    division_id: int = Query(None),
    date_from: str = Query(...),
    date_to: str = Query(...),
    conn=Depends(get_conn),
):
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)

    divisions = await conn.fetch(
        """
        SELECT division_id, name
        FROM division
        ORDER BY name
        """
    )
    entries = []

    if division_id:
        entries = await conn.fetch(
            """
            SELECT
                tch.last_name || ' ' || tch.first_name
                                   AS teacher,
                t.day_of_week,
                t.pair_number,
                t.start_time,
                t.end_time,
                cs.name            AS subject,
                l.lesson_type,
                sg.name            AS study_group,
                r.name             AS room,
                s.entry_date
            FROM schedule_entry s
            JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
            JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
            JOIN lesson l           ON s.lesson_id   = l.lesson_id
            JOIN curriculum_subject cs
                                    ON l.subject_id = cs.subject_id
            JOIN study_group sg     ON s.group_id    = sg.group_id
            LEFT JOIN room r        ON s.room_id     = r.room_id
            WHERE tch.division_id = $1
              AND s.entry_date BETWEEN $2 AND $3
            ORDER BY tch.last_name, t.day_of_week, t.pair_number
            """,
            division_id, d_from, d_to,
        )

    return templates.TemplateResponse(
        "reports/teachers.html",
        {
            "request": request,
            "divisions": divisions,
            "division_id": division_id,
            "date_from": date_from,
            "date_to": date_to,
            "entries": entries,
            "days": {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"},
        },
    )

# Query 5: Сводная загрузка учебных помещений по типу, времени, корпусам
@router.get("/rooms")
async def rooms_report(
    request: Request,
    date_from: str = Query(...),
    date_to: str = Query(...),
    conn=Depends(get_conn),
):
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)

    rows = await conn.fetch(
        """
        SELECT
            b.name             AS building,
            r.room_type,
            r.name             AS room,
            t.day_of_week,
            t.pair_number,
            t.start_time,
            COUNT(s.entry_id)  AS sessions_count
        FROM room r
        JOIN building b         ON r.building_id = b.building_id
        LEFT JOIN schedule_entry s
                                ON s.room_id = r.room_id
                               AND s.entry_date BETWEEN $1 AND $2
        LEFT JOIN timeslot t    ON s.timeslot_id = t.timeslot_id
        GROUP BY b.name, r.room_type, r.name, t.day_of_week, t.pair_number, t.start_time
        ORDER BY b.name, r.room_type, r.name, t.day_of_week, t.pair_number
        """,
        d_from, d_to,
    )

    total = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM schedule_entry
        WHERE entry_date BETWEEN $1 AND $2
          AND room_id IS NOT NULL
        """,
        d_from, d_to,
    )
    if not total:
        total = 1

    return templates.TemplateResponse(
        "reports/rooms.html",
        {
            "request": request,
            "date_from": date_from,
            "date_to": date_to,
            "rows": rows,
            "total": total,
            "days": {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"},
        },
    )

# Queries 6–10: Аудит расписания (проверки ограничений)
@router.get("/audit")
async def audit_report(request: Request, conn=Depends(get_conn)):
    # Query 6: Пересечения в расписании группы
    overlaps = await conn.fetch(
        """
        SELECT
            sg.name  AS group_name,
            t.day_of_week,
            t.pair_number,
            s.entry_date,
            COUNT(*) AS overlaps
        FROM schedule_entry s
        JOIN study_group sg     ON s.group_id    = sg.group_id
        JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
        GROUP BY sg.name, t.day_of_week, t.pair_number, s.entry_date
        HAVING COUNT(*) > 1
        ORDER BY s.entry_date, t.day_of_week, t.pair_number
        """
    )

    # Query 7: Лаборатории только в аудиториях нужного типа
    lab_wrong_rooms = await conn.fetch(
        """
        SELECT
            s.entry_id,
            sg.name   AS group_name,
            cs.name   AS subject,
            r.name    AS room,
            r.room_type
        FROM schedule_entry s
        JOIN lesson l           ON s.lesson_id   = l.lesson_id
        JOIN curriculum_subject cs
                                ON l.subject_id = cs.subject_id
        JOIN study_group sg     ON s.group_id    = sg.group_id
        JOIN room r             ON s.room_id     = r.room_id
        WHERE l.lesson_type = 'lab'
          AND r.room_type NOT IN ('lab', 'computer')
        ORDER BY s.entry_id
        """
    )

    # Query 8: Вместимость помещения достаточна для группы
    capacity_violations = await conn.fetch(
        """
        SELECT
            s.entry_id,
            sg.name           AS group_name,
            sg.student_count,
            r.name            AS room,
            r.capacity
        FROM schedule_entry s
        JOIN study_group sg     ON s.group_id = sg.group_id
        JOIN room r             ON s.room_id  = r.room_id
        WHERE sg.student_count > r.capacity
        ORDER BY s.entry_id
        """
    )

    # Query 9: Преподаватель не более 5 пар в день
    teacher_overload = await conn.fetch(
        """
        SELECT
            tch.last_name || ' ' || tch.first_name
                                  AS teacher,
            s.entry_date,
            COUNT(*)              AS pairs_per_day
        FROM schedule_entry s
        JOIN teacher tch          ON s.teacher_id = tch.teacher_id
        GROUP BY tch.teacher_id, tch.last_name, tch.first_name, s.entry_date
        HAVING COUNT(*) > 5
        ORDER BY s.entry_date DESC, tch.last_name
        """
    )

    # Query 10: Группа не более 5 пар в день
    group_overload = await conn.fetch(
        """
        SELECT
            sg.name      AS group_name,
            s.entry_date,
            COUNT(*)     AS pairs_per_day
        FROM schedule_entry s
        JOIN study_group sg     ON s.group_id = sg.group_id
        GROUP BY sg.group_id, sg.name, s.entry_date
        HAVING COUNT(*) > 5
        ORDER BY s.entry_date DESC, sg.name
        """
    )

    return templates.TemplateResponse(
        "reports/audit.html",
        {
            "request": request,
            "overlaps": overlaps,
            "lab_wrong_rooms": lab_wrong_rooms,
            "capacity_violations": capacity_violations,
            "teacher_overload": teacher_overload,
            "group_overload": group_overload,
            "days": {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"},
        },
    )

# Query 13: Нагрузка преподавателя за семестр (суммарно по типам занятий)
@router.get("/teacher-workload")
async def teacher_workload(
    request: Request,
    semester_start: str = Query(...),
    semester_end: str = Query(...),
    conn=Depends(get_conn),
):
    d_start = date.fromisoformat(semester_start)
    d_end = date.fromisoformat(semester_end)

    rows = await conn.fetch(
        """
        SELECT
            tch.last_name || ' ' || tch.first_name
                               AS teacher,
            l.lesson_type,
            COUNT(*)           AS sessions,
            SUM(l.duration_minutes)
                               AS total_minutes,
            SUM(l.duration_minutes) / 45
                               AS academic_hours
        FROM schedule_entry s
        JOIN teacher tch        ON s.teacher_id = tch.teacher_id
        JOIN lesson l           ON s.lesson_id  = l.lesson_id
        WHERE s.entry_date BETWEEN $1 AND $2
        GROUP BY tch.teacher_id, tch.last_name, tch.first_name, l.lesson_type
        ORDER BY tch.last_name, l.lesson_type
        """,
        d_start, d_end,
    )

    return templates.TemplateResponse(
        "reports/teacher_workload.html",
        {
            "request": request,
            "semester_start": semester_start,
            "semester_end": semester_end,
            "rows": rows,
        },
    )

# Query 15: Расчёт длительности зачёта/экзамена для группы
@router.get("/exam-duration")
async def exam_duration(request: Request, conn=Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT
            sg.name          AS group_name,
            sg.student_count,
            cs.name          AS subject,
            l.lesson_type,
            CASE l.lesson_type
                WHEN 'pass_test' THEN sg.student_count * 10
                WHEN 'exam'      THEN sg.student_count * 20
                ELSE l.duration_minutes
            END              AS required_minutes,
            CASE l.lesson_type
                WHEN 'pass_test' THEN CEIL(sg.student_count * 10.0 / 90)
                WHEN 'exam'      THEN CEIL(sg.student_count * 20.0 / 90)
                ELSE CEIL(l.duration_minutes::NUMERIC / 90)
            END              AS pairs_needed
        FROM schedule_entry s
        JOIN study_group sg     ON s.group_id   = sg.group_id
        JOIN lesson l           ON s.lesson_id  = l.lesson_id
        JOIN curriculum_subject cs
                                ON l.subject_id = cs.subject_id
        WHERE l.lesson_type IN ('exam', 'pass_test')
        ORDER BY sg.name, cs.name
        """
    )

    return templates.TemplateResponse(
        "reports/exam_duration.html",
        {"request": request, "rows": rows},
    )
