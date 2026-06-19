from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import date, datetime, timedelta

from app.auth import require_teacher
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


def mat_schedule_cte() -> str:
    """CTE материализует расписание на диапазон дат из
    schedule_template + schedule_exception. Использует позиционные
    параметры $1 = group_ids (int[] или NULL = все),
    $2 = date_from, $3 = date_to.

    Возвращает строки:
      entry_date, group_id, day_of_week, pair_number, week_parity,
      lesson_id, teacher_id, room_id, is_online, online_link,
      template_id, source ('template'|'replaced'|'added')
    """
    return """
    WITH RECURSIVE dates(d) AS (
        SELECT $2::DATE
        UNION ALL
        SELECT (d + INTERVAL '1 day')::DATE FROM dates WHERE d < $3::DATE
    ),
    cal AS (
        SELECT d,
               EXTRACT(ISODOW FROM d)::INT AS dow,
               (EXTRACT(WEEK FROM d)::INT % 2 = 0) AS is_even,
               COALESCE(wc.is_holiday, FALSE) AS is_holiday
          FROM dates
          LEFT JOIN work_calendar wc ON wc.calendar_date = dates.d
    ),
    cal_working AS (
        SELECT d, dow, is_even FROM cal WHERE NOT is_holiday
    ),
    cancels AS (
        SELECT template_id, entry_date FROM schedule_exception
         WHERE exception_type = 'cancel'
           AND entry_date BETWEEN $2 AND $3
    ),
    replaces AS (
        SELECT * FROM schedule_exception
         WHERE exception_type = 'replace'
           AND entry_date BETWEEN $2 AND $3
    ),
    adds AS (
        SELECT e.entry_date AS d, e.group_id, e.day_of_week, e.pair_number,
               e.week_parity, e.lesson_id, e.teacher_id, e.room_id,
               COALESCE(e.is_online, FALSE) AS is_online,
               e.online_link
          FROM schedule_exception e
         WHERE e.exception_type = 'add'
           AND e.entry_date BETWEEN $2 AND $3
           AND ($1::INT[] IS NULL OR e.group_id = ANY($1::INT[]))
    ),
    template_rows AS (
        SELECT st.*, cw.d
          FROM schedule_template st
          JOIN curriculum_semester sem ON sem.semester_id = st.semester_id
          JOIN cal_working cw ON st.day_of_week = cw.dow
                              AND cw.d BETWEEN sem.start_date AND sem.end_date
         WHERE ($1::INT[] IS NULL OR st.group_id = ANY($1::INT[]))
           AND (st.week_parity = 'all'
                OR (st.week_parity = 'even' AND cw.is_even)
                OR (st.week_parity = 'odd'  AND NOT cw.is_even))
    ),
    mat AS (
        SELECT tr.d AS entry_date, tr.group_id, tr.day_of_week,
               tr.pair_number, tr.week_parity,
               COALESCE(r.lesson_id,   tr.lesson_id)  AS lesson_id,
               COALESCE(r.teacher_id,  tr.teacher_id) AS teacher_id,
               COALESCE(r.room_id,     tr.room_id)    AS room_id,
               COALESCE(r.is_online,   tr.is_online)  AS is_online,
               COALESCE(r.online_link, tr.online_link) AS online_link,
               tr.template_id,
               CASE WHEN r.template_id IS NOT NULL THEN 'replaced' ELSE 'template' END AS source
          FROM template_rows tr
          LEFT JOIN replaces r ON r.template_id = tr.template_id AND r.entry_date = tr.d
         WHERE NOT EXISTS (
                   SELECT 1 FROM cancels c
                    WHERE c.template_id = tr.template_id AND c.entry_date = tr.d
               )
        UNION ALL
        SELECT d, group_id, day_of_week, pair_number, week_parity,
               lesson_id, teacher_id, room_id, is_online, online_link,
               NULL::INT AS template_id, 'added' AS source
          FROM adds
    )
    """


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


# Query 1: Расписание одной учебной группы (редирект на /schedule/)
@router.get("/group")
async def report_group(
    request: Request,
    group_id: int = Query(...),
    date_from: str = Query(...),
    date_to: str = Query(...),
):
    return RedirectResponse(
        url=f"/schedule/?group_ids={group_id}&date_from={date_from}&date_to={date_to}"
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
            mat_schedule_cte() + """
            SELECT DISTINCT ON (m.day_of_week, m.pair_number, sg.name)
                m.day_of_week,
                m.pair_number,
                t.start_time,
                t.end_time,
                sg.name            AS group_name,
                cs.name            AS subject,
                l.lesson_type,
                tch.last_name || ' ' || LEFT(tch.first_name, 1) || '.'
                                   AS teacher_short,
                CASE WHEN m.is_online THEN NULL ELSE r.name END AS room,
                m.is_online,
                m.entry_date
              FROM mat m
              JOIN study_group sg          ON m.group_id  = sg.group_id
              JOIN lesson l                ON m.lesson_id = l.lesson_id
              JOIN curriculum_subject cs   ON l.subject_id = cs.subject_id
              JOIN teacher tch             ON m.teacher_id = tch.teacher_id
              LEFT JOIN room r             ON m.room_id    = r.room_id
              LEFT JOIN timeslot t         ON t.day_of_week = m.day_of_week
                                          AND t.pair_number = m.pair_number
             ORDER BY m.day_of_week, m.pair_number, sg.name, m.entry_date
            """,
            group_ids, d_from, d_to,
        )

    table = {}
    for e in entries:
        key = (e["day_of_week"], e["pair_number"])
        if key not in table:
            table[key] = {}
        if e["group_name"] not in table[key]:
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
            mat_schedule_cte() + """
            SELECT
                sg.name            AS group_name,
                cs.name            AS subject,
                l.lesson_type,
                m.entry_date,
                t.start_time,
                t.end_time,
                m.pair_number,
                tch.last_name || ' ' || LEFT(tch.first_name, 1) || '.'
                                   AS teacher_short,
                CASE WHEN m.is_online THEN NULL ELSE r.name END AS room,
                b.name             AS building,
                m.is_online
              FROM mat m
              JOIN study_group sg          ON m.group_id   = sg.group_id
              JOIN lesson l                ON m.lesson_id  = l.lesson_id
              JOIN curriculum_subject cs   ON l.subject_id = cs.subject_id
              JOIN teacher tch             ON m.teacher_id = tch.teacher_id
              LEFT JOIN room r             ON m.room_id    = r.room_id
              LEFT JOIN building b         ON r.building_id = b.building_id
              LEFT JOIN timeslot t         ON t.day_of_week = m.day_of_week
                                          AND t.pair_number = m.pair_number
             WHERE l.lesson_type IN ('exam', 'pass_test', 'consult')
             ORDER BY m.entry_date, m.pair_number
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
    division_id: str = Query(""),
    date_from: str = Query(...),
    date_to: str = Query(...),
    conn=Depends(get_conn),
):
    if division_id and division_id.lstrip("-").isdigit():
        division_id = int(division_id)
    else:
        division_id = None
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
            mat_schedule_cte() + """
            SELECT
                tch.last_name || ' ' || tch.first_name
                                   AS teacher,
                m.day_of_week,
                m.pair_number,
                t.start_time,
                t.end_time,
                cs.name            AS subject,
                l.lesson_type,
                sg.name            AS study_group,
                CASE WHEN m.is_online THEN NULL ELSE r.name END AS room,
                m.entry_date
              FROM mat m
              JOIN teacher tch            ON m.teacher_id = tch.teacher_id
              JOIN lesson l               ON m.lesson_id  = l.lesson_id
              JOIN curriculum_subject cs  ON l.subject_id = cs.subject_id
              JOIN study_group sg         ON m.group_id   = sg.group_id
              LEFT JOIN room r            ON m.room_id    = r.room_id
              LEFT JOIN timeslot t        ON t.day_of_week = m.day_of_week
                                         AND t.pair_number = m.pair_number
             WHERE tch.division_id = $4
             ORDER BY tch.last_name, m.day_of_week, m.pair_number, m.entry_date
            """,
            None, d_from, d_to, division_id,
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


# Query 5: Сводная загрузка учебных помещений по типу, дню и паре
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
        mat_schedule_cte() + """
        SELECT
            b.name             AS building,
            r.room_type,
            r.name             AS room,
            m.day_of_week,
            m.pair_number,
            COUNT(*)           AS sessions_count
          FROM mat m
          JOIN room r        ON m.room_id = r.room_id
          JOIN building b    ON r.building_id = b.building_id
         WHERE m.room_id IS NOT NULL
         GROUP BY b.name, r.room_type, r.name, m.day_of_week, m.pair_number
         ORDER BY b.name, r.room_type, r.name, m.day_of_week, m.pair_number
        """,
        None, d_from, d_to,
    )

    total = sum(r["sessions_count"] for r in rows) or 1

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
async def audit_report(
    request: Request,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    today = date.today()
    d_from = today - timedelta(days=180)
    d_to = today + timedelta(days=30)

    # Query 6: Пересечения в расписании группы
    overlaps = await conn.fetch(
        mat_schedule_cte() + """
        SELECT
            sg.name            AS group_name,
            m.day_of_week,
            m.pair_number,
            m.entry_date,
            COUNT(*)           AS overlaps
          FROM mat m
          JOIN study_group sg ON m.group_id = sg.group_id
         GROUP BY sg.name, m.day_of_week, m.pair_number, m.entry_date
        HAVING COUNT(*) > 1
        ORDER BY m.entry_date, m.day_of_week, m.pair_number
        """,
        None, d_from, d_to,
    )

    # Query 7: Лаборатории только в аудиториях нужного типа
    lab_wrong_rooms = await conn.fetch(
        """
        SELECT
            st.template_id     AS entry_id,
            sg.name            AS group_name,
            cs.name            AS subject,
            r.name             AS room,
            r.room_type
          FROM schedule_template st
          JOIN lesson l               ON st.lesson_id   = l.lesson_id
          JOIN curriculum_subject cs  ON l.subject_id   = cs.subject_id
          JOIN study_group sg         ON st.group_id    = sg.group_id
          JOIN room r                 ON st.room_id     = r.room_id
         WHERE l.lesson_type = 'lab'
           AND r.room_type NOT IN ('lab', 'computer')
         UNION
        SELECT
            e.exception_id    AS entry_id,
            sg.name           AS group_name,
            cs.name           AS subject,
            r.name            AS room,
            r.room_type
          FROM schedule_exception e
          JOIN lesson l               ON e.lesson_id   = l.lesson_id
          JOIN curriculum_subject cs  ON l.subject_id   = cs.subject_id
          JOIN study_group sg         ON e.group_id    = sg.group_id
          JOIN room r                 ON e.room_id     = r.room_id
         WHERE l.lesson_type = 'lab'
           AND r.room_type NOT IN ('lab', 'computer')
        ORDER BY entry_id
        """,
    )

    # Query 8: Вместимость помещения достаточна для группы
    capacity_violations = await conn.fetch(
        """
        SELECT
            st.template_id     AS entry_id,
            sg.name            AS group_name,
            sg.student_count,
            r.name             AS room,
            r.capacity
          FROM schedule_template st
          JOIN study_group sg ON st.group_id = sg.group_id
          JOIN room r         ON st.room_id  = r.room_id
         WHERE sg.student_count > r.capacity
         UNION
        SELECT
            e.exception_id    AS entry_id,
            sg.name           AS group_name,
            sg.student_count,
            r.name            AS room,
            r.capacity
          FROM schedule_exception e
          JOIN study_group sg ON e.group_id = sg.group_id
          JOIN room r         ON e.room_id  = r.room_id
         WHERE sg.student_count > r.capacity
         ORDER BY entry_id
        """,
    )

    # Query 9: Преподаватель не более 5 пар в день
    teacher_overload = await conn.fetch(
        mat_schedule_cte() + """
        SELECT
            tch.last_name || ' ' || tch.first_name
                                  AS teacher,
            m.entry_date,
            COUNT(*)              AS pairs_per_day
          FROM mat m
          JOIN teacher tch ON m.teacher_id = tch.teacher_id
         GROUP BY tch.teacher_id, tch.last_name, tch.first_name, m.entry_date
        HAVING COUNT(*) > 5
        ORDER BY m.entry_date DESC, tch.last_name
        """,
        None, d_from, d_to,
    )

    # Query 10: Группа не более 5 пар в день
    group_overload = await conn.fetch(
        mat_schedule_cte() + """
        SELECT
            sg.name      AS group_name,
            m.entry_date,
            COUNT(*)     AS pairs_per_day
          FROM mat m
          JOIN study_group sg ON m.group_id = sg.group_id
         GROUP BY sg.group_id, sg.name, m.entry_date
         HAVING COUNT(*) > 5
         ORDER BY m.entry_date DESC, sg.name
        """,
        None, d_from, d_to,
    )

    # Query 11: Окна между парами > 1,5 астрономического часа (90 минут)
    # Если у одной группы/препода в один день есть пара A и пара B,
    # |pair(A)-pair(B)| >= 2, и между ними по времени > 90 минут — это окно.
    # (Учитываем только соседние по времени пары в этот день.)
    long_gaps = await conn.fetch(
        mat_schedule_cte() + """,
        day_pairs AS (
            SELECT m.entry_date, m.group_id, m.teacher_id,
                   m.day_of_week, m.pair_number,
                   m.template_id,
                   ts.start_time, ts.end_time
              FROM mat m
              JOIN timeslot ts ON ts.day_of_week = m.day_of_week
                               AND ts.pair_number = m.pair_number
        ),
        gaps AS (
            SELECT a.entry_date,
                   a.group_id, a.teacher_id,
                   a.pair_number AS first_pair, b.pair_number AS second_pair,
                   b.start_time - a.end_time AS gap_interval
              FROM day_pairs a
              JOIN day_pairs b
                ON a.entry_date = b.entry_date
               AND a.group_id   = b.group_id
               AND a.pair_number < b.pair_number
               AND NOT EXISTS (
                     SELECT 1 FROM day_pairs c
                      WHERE c.entry_date = a.entry_date
                        AND c.group_id   = a.group_id
                        AND c.pair_number > a.pair_number
                        AND c.pair_number < b.pair_number
               )
        )
        SELECT g.entry_date,
               sg.name AS group_name,
               tch.last_name || ' ' || tch.first_name AS teacher,
               g.first_pair, g.second_pair,
               EXTRACT(EPOCH FROM g.gap_interval)::INT / 60 AS gap_minutes
          FROM gaps g
          JOIN study_group sg ON g.group_id = sg.group_id
          JOIN teacher tch   ON g.teacher_id = tch.teacher_id
         WHERE EXTRACT(EPOCH FROM g.gap_interval)::INT / 60 > 90
         ORDER BY g.entry_date, sg.name
        """,
        None, d_from, d_to,
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
            "long_gaps": long_gaps,
            "days": {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"},
        },
    )


# Query 13: Нагрузка преподавателя за семестр
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
        mat_schedule_cte() + """
        SELECT
            tch.last_name || ' ' || tch.first_name
                               AS teacher,
            l.lesson_type,
            COUNT(*)           AS sessions,
            SUM(l.duration_minutes)
                               AS total_minutes,
            ROUND(SUM(l.duration_minutes)::NUMERIC / 45, 2)
                               AS academic_hours
          FROM mat m
          JOIN teacher tch  ON m.teacher_id = tch.teacher_id
          JOIN lesson l     ON m.lesson_id  = l.lesson_id
         GROUP BY tch.teacher_id, tch.last_name, tch.first_name, l.lesson_type
         ORDER BY tch.last_name, l.lesson_type
        """,
        None, d_start, d_end,
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
          FROM lesson l
          JOIN curriculum_subject cs ON l.subject_id   = cs.subject_id
          JOIN study_group sg        ON sg.semester_id = cs.semester_id
         WHERE l.lesson_type IN ('exam', 'pass_test')
         ORDER BY sg.name, cs.name
        """,
    )

    return templates.TemplateResponse(
        "reports/exam_duration.html",
        {"request": request, "rows": rows},
    )
