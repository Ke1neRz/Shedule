from fastapi import APIRouter, Request, Form, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse
import asyncpg
from datetime import date, timedelta

from app.auth import require_teacher
from app.db import get_conn
from app.templates_setup import templates

router = APIRouter()


def _parity_matches(parity: str, is_even: bool) -> bool:
    return parity == "all" or (parity == "even" and is_even) or (parity == "odd" and not is_even)


def _parities_overlap(a: str, b: str) -> bool:
    """Пересекаются ли два значения week_parity (any/all/even/odd).
    'all' пересекается с любым; 'even' с 'all' и 'even'; 'odd' с 'all' и 'odd'.
    'even' и 'odd' не пересекаются."""
    if a == "all" or b == "all":
        return True
    return a == b


async def _validate_constraints(
    conn,
    *,
    semester_id: int,
    group_id: int,
    day_of_week: int,
    pair_number: int,
    week_parity: str,
    lesson_id: int,
    teacher_id: int,
    room_id: int | None,
    is_online: bool,
    exclude_template_id: int | None = None,
    exception_entry_date: date | None = None,
    is_exception_add: bool = False,
) -> list[str]:
    errors: list[str] = []
    if week_parity not in ("all", "even", "odd"):
        week_parity = "all"

    # ---- 1. Учебное поручение (teacher_lesson) ----
    has_assignment = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM teacher_lesson "
        "WHERE teacher_id = $1 AND lesson_id = $2)",
        teacher_id, lesson_id,
    )
    if not has_assignment:
        errors.append(
            "У преподавателя нет учебного поручения на этот вид занятия "
            "(отсутствует запись в teacher_lesson). Назначьте поручение во вкладке "
            "«Занятия» преподавателя."
        )

    # ---- 2. Вместимость аудитории ----
    if room_id is not None and not is_online:
        cap_row = await conn.fetchrow(
            "SELECT r.capacity, sg.student_count "
            "  FROM room r, study_group sg "
            " WHERE r.room_id = $1 AND sg.group_id = $2",
            room_id, group_id,
        )
        if cap_row and cap_row["student_count"] > cap_row["capacity"]:
            errors.append(
                f"Вместимость аудитории ({cap_row['capacity']}) меньше количества "
                f"студентов в группе ({cap_row['student_count']})."
            )

    # Подзапрос для week_parity overlap — пересекаются ли чётности двух
    # записей. (A='all' ∨ B='all' ∨ A=B)
    parity_overlap = (
        "(st.week_parity = 'all' OR st.week_parity = $%d OR $%d = 'all')"
    )

    if not is_exception_add:
        # ===== Проверки для schedule_template / replace =====

        # ---- 3-5. Пересечения: преподаватель / аудитория / группа ----
        # В одном семестре, в тот же день+пара, пересекающаяся чётность.
        exclude_clause = ""
        if exclude_template_id is not None:
            exclude_clause = " AND st.template_id <> $%d" % 9

        # Преподаватель
        t_conflict = await conn.fetch(
            f"""
            SELECT st.template_id, sg.name AS group_name,
                   cs.name AS subject_name, st.week_parity
              FROM schedule_template st
              JOIN lesson l ON st.lesson_id = l.lesson_id
              JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
              JOIN study_group sg ON st.group_id = sg.group_id
             WHERE st.semester_id = $1
               AND st.day_of_week = $2
               AND st.pair_number = $3
               AND st.teacher_id  = $4
               AND {parity_overlap % (5, 6)}
               {exclude_clause}
            """,
            semester_id, day_of_week, pair_number,
            teacher_id, week_parity, week_parity,
        )
        if t_conflict:
            tpl = t_conflict[0]
            errors.append(
                f"Преподаватель уже занят в это время: "
                f"группа «{tpl['group_name']}», предмет «{tpl['subject_name']}», "
                f"чётность «{tpl['week_parity']}»."
            )

        # Аудитория
        if room_id is not None and not is_online:
            r_conflict = await conn.fetch(
                f"""
                SELECT st.template_id, sg.name AS group_name,
                       cs.name AS subject_name, st.week_parity
                  FROM schedule_template st
                  JOIN lesson l ON st.lesson_id = l.lesson_id
                  JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
                  JOIN study_group sg ON st.group_id = sg.group_id
                 WHERE st.semester_id = $1
                   AND st.day_of_week = $2
                   AND st.pair_number = $3
                   AND st.room_id     = $4
                   AND {parity_overlap % (5, 6)}
                   {exclude_clause}
                """,
                semester_id, day_of_week, pair_number,
                room_id, week_parity, week_parity,
            )
            if r_conflict:
                tpl = r_conflict[0]
                errors.append(
                    f"Аудитория уже занята в это время: "
                    f"группа «{tpl['group_name']}», предмет «{tpl['subject_name']}», "
                    f"чётность «{tpl['week_parity']}»."
                )

        # Группа (дубликат UNIQUE — но явно)
        g_conflict = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM schedule_template st
             WHERE st.semester_id = $1
               AND st.day_of_week = $2
               AND st.pair_number = $3
               AND st.group_id    = $4
               AND {parity_overlap % (5, 6)}
               {exclude_clause}
            """,
            semester_id, day_of_week, pair_number,
            group_id, week_parity, week_parity,
        )
        if g_conflict and g_conflict > 0:
            errors.append(
                "У группы уже есть пара в этом слоте (день+пара+чётность)."
            )

        # ---- 6. Лимит 5 пар в день (по этой чётности) ----
        teacher_count_sql = f"""
            SELECT COUNT(*) FROM schedule_template st
             WHERE st.semester_id = $1
               AND st.day_of_week = $2
               AND st.teacher_id  = $3
               AND {parity_overlap % (4, 5)}
               {exclude_clause}
        """
        t_count = await conn.fetchval(
            teacher_count_sql,
            semester_id, day_of_week, teacher_id,
            week_parity, week_parity,
        )
        if t_count and t_count >= 5:
            errors.append(
                f"У преподавателя уже {t_count} пар в этот день с такой "
                f"чётностью. Лимит по ТК — не более 5 пар в день."
            )

        group_count = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM schedule_template st
             WHERE st.semester_id = $1
               AND st.day_of_week = $2
               AND st.group_id    = $3
               AND {parity_overlap % (4, 5)}
               {exclude_clause}
            """,
            semester_id, day_of_week, group_id,
            week_parity, week_parity,
        )
        if group_count and group_count >= 5:
            errors.append(
                f"У группы уже {group_count} пар в этот день с такой "
                f"чётностью. Лимит — не более 5 пар в день."
            )

        # ---- 7. Перемещение между корпусами ----
        if room_id is not None and not is_online:
            await _check_building_distance(
                conn, errors, semester_id=semester_id,
                group_id=group_id, teacher_id=teacher_id,
                day_of_week=day_of_week, pair_number=pair_number,
                week_parity=week_parity, room_id=room_id,
                exclude_template_id=exclude_template_id,
            )
    else:
        # ===== Проверки для exception типа 'add' (на конкретную дату) =====
        if exception_entry_date is None:
            errors.append("Для исключения типа add требуется конкретная дата.")
            return errors
        dow = exception_entry_date.weekday() + 1
        is_even = exception_entry_date.isocalendar()[1] % 2 == 0

        # Для replace/add: проверим, что на эту дату не пересекается с
        # шаблоном (с учётом чётности даты).
        # Преподаватель занят шаблоном
        tpl_t_busy = await conn.fetch(
            """
            SELECT sg.name AS group_name, cs.name AS subject_name,
                   st.week_parity
              FROM schedule_template st
              JOIN lesson l ON st.lesson_id = l.lesson_id
              JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
              JOIN study_group sg ON st.group_id = sg.group_id
             WHERE st.teacher_id = $1
               AND st.day_of_week = $2
               AND st.pair_number = $3
               AND (st.week_parity = 'all'
                    OR (st.week_parity = 'even' AND $4)
                    OR (st.week_parity = 'odd'  AND NOT $4))
               AND ($5::INT IS NULL OR st.template_id <> $5)
            """,
            teacher_id, dow, pair_number, is_even,
            exclude_template_id,
        )
        if tpl_t_busy:
            tpl = tpl_t_busy[0]
            errors.append(
                f"Преподаватель уже ведёт основную пару в это время: "
                f"группа «{tpl['group_name']}», предмет «{tpl['subject_name']}»."
            )

        # Другие add на ту же дату+слот с тем же преподом
        add_t_busy = await conn.fetchval(
            """
            SELECT COUNT(*) FROM schedule_exception
             WHERE exception_type = 'add' AND teacher_id = $1
               AND entry_date = $2 AND day_of_week = $3
               AND pair_number = $4
               AND ($5::INT IS NULL OR exception_id <> $5)
            """,
            teacher_id, exception_entry_date, dow, pair_number,
            exclude_template_id,
        )
        if add_t_busy and add_t_busy > 0:
            errors.append(
                "Преподаватель уже ведёт другую дополнительную пару "
                "в это же время."
            )

        # Группа: другие add на ту же дату+слот
        add_g_busy = await conn.fetchval(
            """
            SELECT COUNT(*) FROM schedule_exception
             WHERE exception_type = 'add' AND group_id = $1
               AND entry_date = $2 AND day_of_week = $3
               AND pair_number = $4
               AND ($5::INT IS NULL OR exception_id <> $5)
            """,
            group_id, exception_entry_date, dow, pair_number,
            exclude_template_id,
        )
        if add_g_busy and add_g_busy > 0:
            errors.append(
                "У группы уже есть дополнительная пара в этом слоте на эту дату."
            )

        # Аудитория занята другой add
        if room_id is not None and not is_online:
            add_r_busy = await conn.fetchval(
                """
                SELECT COUNT(*) FROM schedule_exception
                 WHERE exception_type = 'add' AND room_id = $1
                   AND entry_date = $2 AND pair_number = $3
                   AND ($4::INT IS NULL OR exception_id <> $4)
                """,
                room_id, exception_entry_date, pair_number, exclude_template_id,
            )
            if add_r_busy and add_r_busy > 0:
                errors.append(
                    "Аудитория занята другой дополнительной парой в это время."
                )
            tpl_r_busy = await conn.fetch(
                """
                SELECT sg.name AS group_name, cs.name AS subject_name,
                       st.week_parity
                  FROM schedule_template st
                  JOIN lesson l ON st.lesson_id = l.lesson_id
                  JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
                  JOIN study_group sg ON st.group_id = sg.group_id
                 WHERE st.room_id = $1
                   AND st.day_of_week = $2
                   AND st.pair_number = $3
                   AND (st.week_parity = 'all'
                        OR (st.week_parity = 'even' AND $4)
                        OR (st.week_parity = 'odd'  AND NOT $4))
                """,
                room_id, dow, pair_number, is_even,
            )
            if tpl_r_busy:
                tpl = tpl_r_busy[0]
                errors.append(
                    f"Аудитория занята основным расписанием в это время: "
                    f"группа «{tpl['group_name']}», предмет «{tpl['subject_name']}»."
                )

        # Лимит 5 пар в день у преподавателя на эту дату
        # Считаем все шаблоны (с учётом чётности) + другие add на эту дату.
        t_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM schedule_template st
             WHERE st.teacher_id = $1
               AND st.day_of_week = $2
               AND (st.week_parity = 'all'
                    OR (st.week_parity = 'even' AND $3)
                    OR (st.week_parity = 'odd'  AND NOT $3))
            """,
            teacher_id, dow, is_even,
        )
        add_t_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM schedule_exception
             WHERE exception_type = 'add' AND teacher_id = $1
               AND entry_date = $2
               AND ($3::INT IS NULL OR exception_id <> $3)
            """,
            teacher_id, exception_entry_date, exclude_template_id,
        )
        teacher_total = (t_count or 0) + (add_t_count or 0)
        if teacher_total >= 5:
            errors.append(
                f"У преподавателя {teacher_total} пар в этот день с учётом "
                f"чётности. Лимит по ТК — не более 5 пар в день."
            )

        g_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM schedule_template st
             WHERE st.group_id = $1
               AND st.day_of_week = $2
               AND (st.week_parity = 'all'
                    OR (st.week_parity = 'even' AND $3)
                    OR (st.week_parity = 'odd'  AND NOT $3))
            """,
            group_id, dow, is_even,
        )
        add_g_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM schedule_exception
             WHERE exception_type = 'add' AND group_id = $1
               AND entry_date = $2
               AND ($3::INT IS NULL OR exception_id <> $3)
            """,
            group_id, exception_entry_date, exclude_template_id,
        )
        group_total = (g_count or 0) + (add_g_count or 0)
        if group_total >= 5:
            errors.append(
                f"У группы {group_total} пар в этот день с учётом чётности. "
                f"Лимит — не более 5 пар в день."
            )

        # Перемещение между корпусами (для add — на конкретную дату)
        if room_id is not None and not is_online:
            # Соседняя пара у препода/группы в этот день (по шаблону или add)
            neigh = await conn.fetch(
                f"""
                SELECT st.pair_number AS other_pair, st.room_id AS other_room,
                       r2.building_id AS other_building, r.building_id AS my_building,
                       st.week_parity
                  FROM schedule_template st
                  JOIN room r2 ON r2.room_id = st.room_id
                  CROSS JOIN (SELECT building_id FROM room WHERE room_id = $1) r
                 WHERE st.semester_id = $2
                   AND st.day_of_week = $3
                   AND (st.teacher_id = $4 OR st.group_id = $5)
                   AND st.room_id IS NOT NULL
                   AND st.room_id <> $1
                   AND ABS(st.pair_number - $6) = 1
                   AND (st.week_parity = 'all'
                        OR (st.week_parity = 'even' AND $7)
                        OR (st.week_parity = 'odd'  AND NOT $7))
                """,
                room_id, semester_id, dow,
                teacher_id, group_id, pair_number, is_even,
            )
            for n in neigh:
                other_b = n["other_building"]
                my_b = n["my_building"]
                if other_b and my_b and other_b != my_b:
                    dist = await conn.fetchval(
                        "SELECT distance_minutes FROM building_distance "
                        "WHERE from_building_id = $1 AND to_building_id = $2",
                        my_b, other_b,
                    )
                    if dist is None:
                        dist = await conn.fetchval(
                            "SELECT distance_minutes FROM building_distance "
                            "WHERE from_building_id = $1 AND to_building_id = $2",
                            other_b, my_b,
                        )
                    if dist is not None and dist > 90:
                        errors.append(
                            f"Между этой парой ({pair_number}) и соседней "
                            f"парой ({n['other_pair']}) — переход {dist} мин "
                            f"между корпусами. Допускается не более 90 минут."
                        )

    return errors


async def _check_building_distance(
    conn, errors,
    *,
    semester_id: int,
    group_id: int,
    teacher_id: int,
    day_of_week: int,
    pair_number: int,
    week_parity: str,
    room_id: int,
    exclude_template_id: int | None,
) -> None:
    """Проверка возможности перемещения между корпусами для соседних пар
    (±1 по номеру) у одного преподавателя или группы в этот день."""
    rows = await conn.fetch(
        """
        SELECT st.pair_number AS other_pair,
               st.week_parity AS other_parity,
               r2.building_id AS other_building,
               r.building_id  AS my_building
          FROM schedule_template st
          JOIN room r2 ON r2.room_id = st.room_id
         CROSS JOIN (SELECT building_id FROM room WHERE room_id = $1) r
         WHERE st.semester_id = $2
           AND st.day_of_week = $3
           AND (st.teacher_id = $4 OR st.group_id = $5)
           AND st.room_id IS NOT NULL
           AND st.room_id <> $1
           AND ABS(st.pair_number - $6) = 1
           AND (st.week_parity = 'all'
                OR st.week_parity = $7
                OR $7 = 'all')
           AND ($8::INT IS NULL OR st.template_id <> $8)
        """,
        room_id, semester_id, day_of_week,
        teacher_id, group_id, pair_number, week_parity,
        exclude_template_id,
    )
    for n in rows:
        other_b = n["other_building"]
        my_b = n["my_building"]
        if other_b and my_b and other_b != my_b:
            dist = await conn.fetchval(
                "SELECT distance_minutes FROM building_distance "
                "WHERE from_building_id = $1 AND to_building_id = $2",
                my_b, other_b,
            )
            if dist is None:
                dist = await conn.fetchval(
                    "SELECT distance_minutes FROM building_distance "
                    "WHERE from_building_id = $1 AND to_building_id = $2",
                    other_b, my_b,
                )
            if dist is not None and dist > 90:
                errors.append(
                    f"Между этой парой ({pair_number}) и соседней парой "
                    f"({n['other_pair']}) — переход {dist} мин между корпусами. "
                    f"Допускается не более 90 минут."
                )


def _generate_schedule(template_rows, exception_rows, group_ids, d_from, d_to, calendar_rows=None):
    """Генерация расписания из шаблона + исключений.
    Возвращает {(date, day_of_week, pair_number): [entries]}.
    calendar_rows: список словарей {calendar_date, is_working, is_holiday}
    из work_calendar. Если день помечен как нерабочий (is_working=FALSE) или
    праздничный (is_holiday=TRUE), пары по шаблону НЕ создаются.
    Дни без записи в календаре считаются рабочими (если только не воскресенье)."""
    schedule = {}

    cal_by_date = {}
    if calendar_rows:
        for c in calendar_rows:
            cal_by_date[c["calendar_date"]] = c

    ex_by_tpl_date = {}
    add_by_date_group = {}
    for ex in exception_rows:
        if ex["exception_type"] in ("replace", "cancel") and ex["template_id"]:
            ex_by_tpl_date.setdefault((ex["template_id"], ex["entry_date"]), []).append(ex)
        elif ex["exception_type"] == "add":
            add_by_date_group.setdefault((ex["entry_date"], ex["group_id"]), []).append(ex)

    cur = d_from
    while cur <= d_to:
        dow = cur.weekday() + 1
        is_even = cur.isocalendar()[1] % 2 == 0

        # По производственному календарю: воскресенье — всегда выходной,
        # явные is_working=FALSE или is_holiday=TRUE — нерабочие дни.
        cal_entry = cal_by_date.get(cur)
        is_workday = True
        if cal_entry is not None:
            if not cal_entry["is_working"] or cal_entry["is_holiday"]:
                is_workday = False
        # Если дня нет в календаре — опираемся только на DOW (воскресенье=7 не входит в 1..6)
        # Здесь мы уже ограничены dow=1..6 (Пн..Сб), но защищаемся от воскресенья.
        if dow < 1 or dow > 6:
            is_workday = False

        if not is_workday:
            cur += timedelta(days=1)
            continue

        for t in template_rows:
            if t["day_of_week"] != dow:
                continue
            if t["group_id"] not in group_ids:
                continue
            if not _parity_matches(t["week_parity"], is_even):
                continue

            ex_list = ex_by_tpl_date.get((t["template_id"], cur), [])
            skip = False
            entry = dict(t)
            entry["entry_date"] = cur
            entry["source"] = "template"
            entry["exception_note"] = None
            for ex in ex_list:
                if ex["exception_type"] == "cancel":
                    skip = True
                    break
                if ex["exception_type"] == "replace":
                    if ex["teacher_id"]:
                        entry["teacher_id"] = ex["teacher_id"]
                        entry["teacher_last"] = ex.get("teacher_last")
                        entry["teacher_first"] = ex.get("teacher_first")
                        entry["teacher_middle"] = ex.get("teacher_middle")
                    if ex["room_id"]:
                        entry["room_id"] = ex["room_id"]
                        entry["room_name"] = ex.get("room_name")
                        entry["building_name"] = ex.get("building_name")
                    if ex["lesson_id"]:
                        entry["lesson_id"] = ex["lesson_id"]
                        entry["subject_name"] = ex.get("subject_name")
                        entry["lesson_type"] = ex.get("lesson_type")
                        entry["duration_minutes"] = ex.get("duration_minutes")
                    if ex["is_online"] is not None:
                        entry["is_online"] = ex["is_online"]
                    if ex["online_link"]:
                        entry["online_link"] = ex["online_link"]
                    entry["exception_note"] = ex.get("note")
                    entry["source"] = "replaced"

            if skip:
                continue

            schedule.setdefault((cur, dow, t["pair_number"]), []).append(entry)

        for g_id in group_ids:
            for ex in add_by_date_group.get((cur, g_id), []):
                if not _parity_matches(ex.get("week_parity") or "all", is_even):
                    continue
                entry = {
                    "template_id": None,
                    "group_id": g_id,
                    "day_of_week": ex["day_of_week"],
                    "pair_number": ex["pair_number"],
                    "week_parity": ex.get("week_parity") or "all",
                    "lesson_id": ex["lesson_id"],
                    "subject_name": ex.get("subject_name"),
                    "lesson_type": ex.get("lesson_type"),
                    "duration_minutes": ex.get("duration_minutes"),
                    "teacher_id": ex["teacher_id"],
                    "teacher_last": ex.get("teacher_last"),
                    "teacher_first": ex.get("teacher_first"),
                    "teacher_middle": ex.get("teacher_middle"),
                    "room_id": ex["room_id"],
                    "room_name": ex.get("room_name"),
                    "building_name": ex.get("building_name"),
                    "is_online": ex.get("is_online") or False,
                    "online_link": ex.get("online_link"),
                    "entry_date": cur,
                    "source": "added",
                    "exception_note": ex.get("note"),
                }
                schedule.setdefault((cur, ex["day_of_week"], ex["pair_number"]), []).append(entry)

        cur += timedelta(days=1)

    return schedule


# ===================== INDEX (генерация расписания) =====================

@router.get("/")
async def schedule_index(
    request: Request,
    group_ids: list[int] = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    conn=Depends(get_conn),
):
    groups = await conn.fetch("SELECT group_id, name FROM study_group ORDER BY name")
    if not group_ids:
        group_ids = [g["group_id"] for g in groups]

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    saturday = monday + timedelta(days=5)
    if not date_from:
        date_from = monday.isoformat()
    if not date_to:
        date_to = saturday.isoformat()
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)

    template_rows = await conn.fetch(
        """
        SELECT st.template_id, st.semester_id, st.group_id, st.day_of_week,
               st.pair_number, st.week_parity, st.lesson_id, st.teacher_id,
               st.room_id, st.is_online, st.online_link,
               l.lesson_type, l.duration_minutes,
               cs.name AS subject_name,
               tch.last_name AS teacher_last,
               tch.first_name AS teacher_first,
               tch.middle_name AS teacher_middle,
               r.name AS room_name, b.name AS building_name
          FROM schedule_template st
          JOIN lesson l ON st.lesson_id = l.lesson_id
          JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
          JOIN teacher tch ON st.teacher_id = tch.teacher_id
          LEFT JOIN room r ON st.room_id = r.room_id
          LEFT JOIN building b ON r.building_id = b.building_id
         WHERE st.group_id = ANY($1::int[])
        """,
        group_ids,
    )

    exception_rows = await conn.fetch(
        """
        SELECT e.exception_id, e.exception_type, e.template_id, e.group_id,
               e.day_of_week, e.pair_number, e.week_parity, e.entry_date,
               e.lesson_id, e.teacher_id, e.room_id, e.is_online,
               e.online_link, e.note,
               l.lesson_type, l.duration_minutes,
               cs.name AS subject_name,
               tch.last_name AS teacher_last,
               tch.first_name AS teacher_first,
               tch.middle_name AS teacher_middle,
               r.name AS room_name, b.name AS building_name
          FROM schedule_exception e
          LEFT JOIN lesson l ON e.lesson_id = l.lesson_id
          LEFT JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
           LEFT JOIN teacher tch ON e.teacher_id = tch.teacher_id
           LEFT JOIN room r ON e.room_id = r.room_id
           LEFT JOIN building b ON r.building_id = b.building_id
          WHERE e.entry_date BETWEEN $1 AND $2
           AND (
                e.template_id IN (SELECT template_id FROM schedule_template
                                   WHERE group_id = ANY($3::int[]))
             OR e.group_id = ANY($3::int[])
           )
        """,
        d_from, d_to, group_ids,
    )

    calendar_rows = await conn.fetch(
        """
        SELECT calendar_date, is_working, is_holiday, note
          FROM work_calendar
         WHERE calendar_date BETWEEN $1 AND $2
        """,
        d_from, d_to,
    )

    academic_rows = await conn.fetch(
        """
        SELECT sg.group_id AS study_group_id,
               ag.academic_group_id,
               ag.group_number,
               c.name AS curriculum_name
          FROM study_group sg
          JOIN curriculum_semester sm ON sg.semester_id = sm.semester_id
          JOIN curriculum c           ON sm.curriculum_id = c.curriculum_id
          LEFT JOIN study_group_academic_group sag
                    ON sag.study_group_id = sg.group_id
          LEFT JOIN academic_group ag  ON sag.academic_group_id = ag.academic_group_id
         WHERE sg.group_id = ANY($1::int[])
         ORDER BY c.admission_year DESC, ag.group_number
        """,
        group_ids,
    )
    academic_by_sg = {}
    for r in academic_rows:
        academic_by_sg.setdefault(r["study_group_id"], []).append(r)

    schedule = _generate_schedule(
        template_rows, exception_rows, group_ids, d_from, d_to, calendar_rows,
    )

    table = {d: {p: [] for p in range(1, 9)} for d in range(1, 7)}
    for (d_date, dow, pn), entries in schedule.items():
        table[dow][pn].extend(entries)

    group_map = {g["group_id"]: g["name"] for g in groups}

    day_names = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"}
    cal_by_date = {c["calendar_date"]: c for c in calendar_rows}

    day_info = {}
    for d in range(1, 7):
        d_date = d_from + timedelta(days=d - 1)
        cal_entry = cal_by_date.get(d_date)
        is_nonworking = False
        nonworking_reason = None
        if cal_entry and (not cal_entry["is_working"] or cal_entry["is_holiday"]):
            is_nonworking = True
            nonworking_reason = cal_entry["note"] or (
                "Праздник" if cal_entry["is_holiday"] else "Нерабочий день"
            )
        day_info[d] = {
            "name": day_names[d],
            "date": d_date.isoformat(),
            "is_today": d_date == today,
            "is_nonworking": is_nonworking,
            "nonworking_reason": nonworking_reason,
        }

    academic_titles = {}
    for sg_id, rows in academic_by_sg.items():
        academic_numbers = [r["group_number"] for r in rows if r["group_number"]]
        curricula = sorted({r["curriculum_name"] for r in rows if r["curriculum_name"]})
        if academic_numbers:
            academic_titles[sg_id] = ", ".join(academic_numbers)
        elif curricula:
            academic_titles[sg_id] = curricula[0]
        else:
            academic_titles[sg_id] = group_map.get(sg_id, "")

    group_colors = [
        "#1976d2", "#7b1fa2", "#388e3c", "#f57c00", "#c2185b",
        "#00796b", "#689f38", "#fbc02d", "#e64a19", "#5e35b1",
    ]
    lesson_type_labels = {
        "lecture": "Лекция", "practice": "Практика", "lab": "Лабораторная",
        "exam": "Экзамен", "pass_test": "Зачёт", "consult": "Консультация",
        "internship": "Практика",
    }

    return templates.TemplateResponse(
        "schedule/index.html",
        {
            "request": request,
            "groups": groups,
            "group_ids": group_ids,
            "group_map": group_map,
            "academic_titles": academic_titles,
            "date_from": date_from,
            "date_to": date_to,
            "table": table,
            "day_info": day_info,
            "group_colors": group_colors,
            "lesson_type_labels": lesson_type_labels,
            "prev_from": (d_from - timedelta(days=7)).isoformat(),
            "prev_to": (d_to - timedelta(days=7)).isoformat(),
            "next_from": (d_from + timedelta(days=7)).isoformat(),
            "next_to": (d_to + timedelta(days=7)).isoformat(),
            "cur_from": monday.isoformat(),
            "cur_to": saturday.isoformat(),
            "today_iso": today.isoformat(),
        },
    )


# ===================== TEMPLATES CRUD =====================

@router.get("/templates")
async def list_templates(
    request: Request, group_id: str = Query(""), conn=Depends(get_conn),
):
    group_id = _opt_int(group_id)
    groups = await conn.fetch("SELECT group_id, name FROM study_group ORDER BY name")
    if not group_id and groups:
        group_id = groups[0]["group_id"]

    templates_rows = []
    if group_id:
        templates_rows = await conn.fetch(
            """
            SELECT st.*,
                   l.lesson_type, l.duration_minutes,
                   cs.name AS subject_name,
                   tch.last_name, tch.first_name, tch.middle_name,
                   r.name AS room_name, b.name AS building_name,
                   sm.semester_number, sm.academic_year, c.name AS curriculum_name
              FROM schedule_template st
              JOIN curriculum_semester sm ON st.semester_id = sm.semester_id
              JOIN curriculum c ON sm.curriculum_id = c.curriculum_id
              JOIN lesson l ON st.lesson_id = l.lesson_id
              JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
              JOIN teacher tch ON st.teacher_id = tch.teacher_id
              LEFT JOIN room r ON st.room_id = r.room_id
              LEFT JOIN building b ON r.building_id = b.building_id
             WHERE st.group_id = $1
             ORDER BY sm.semester_number, st.day_of_week, st.pair_number
            """,
            group_id,
        )

    return templates.TemplateResponse(
        "schedule/templates_list.html",
        {
            "request": request,
            "groups": groups,
            "group_id": group_id,
            "templates": templates_rows,
            "selected_group": next((g for g in groups if g["group_id"] == group_id), None),
        },
    )


async def _load_form_data(conn):
    groups = await conn.fetch("SELECT group_id, name FROM study_group ORDER BY name")
    semesters = await conn.fetch(
        """
        SELECT sm.semester_id, sm.semester_number, sm.academic_year,
               c.name AS curriculum_name,
               (c.name || ' / ' || sm.semester_number || '-й семестр / ' || sm.academic_year) AS label
          FROM curriculum_semester sm
          JOIN curriculum c ON sm.curriculum_id = c.curriculum_id
         ORDER BY c.admission_year DESC, sm.semester_number
        """,
    )
    teachers = await conn.fetch(
        "SELECT teacher_id, last_name || ' ' || first_name AS full_name FROM teacher ORDER BY last_name"
    )
    lessons = await conn.fetch(
        """
        SELECT l.lesson_id, cs.name AS subject_name, l.lesson_type, l.duration_minutes
          FROM lesson l
          JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
         ORDER BY cs.name, l.lesson_type
        """,
    )
    rooms = await conn.fetch(
        "SELECT room_id, name || ' (' || room_type || ', ' || capacity || ' чел)' AS label FROM room ORDER BY name"
    )
    return groups, semesters, teachers, lessons, rooms


@router.get("/templates/add")
async def add_template_form(
    request: Request,
    group_id: str = Query(""),
    semester_id: str = Query(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    groups, semesters, teachers, lessons, rooms = await _load_form_data(conn)
    return templates.TemplateResponse(
        "schedule/template_form.html",
        {
            "request": request,
            "template": None,
            "groups": groups, "semesters": semesters,
            "teachers": teachers, "lessons": lessons, "rooms": rooms,
            "preselected_group": _opt_int(group_id),
            "preselected_semester": _opt_int(semester_id),
        },
    )


@router.post("/templates/add")
async def add_template_submit(
    semester_id: int = Form(...),
    group_id: int = Form(...),
    day_of_week: int = Form(...),
    pair_number: int = Form(...),
    week_parity: str = Form("all"),
    lesson_id: int = Form(...),
    teacher_id: int = Form(...),
    room_id: int = Form(None),
    is_online: bool = Form(False),
    online_link: str = Form(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    if is_online:
        room_id = None

    errors = await _validate_constraints(
        conn,
        semester_id=semester_id,
        group_id=group_id,
        day_of_week=day_of_week,
        pair_number=pair_number,
        week_parity=week_parity,
        lesson_id=lesson_id,
        teacher_id=teacher_id,
        room_id=room_id,
        is_online=is_online,
    )
    if errors:
        body = "<h1>Ошибки при создании шаблона</h1><ul>"
        for e in errors:
            body += f"<li>{e}</li>"
        body += "</ul>"
        body += f"<a href='/schedule/templates?group_id={group_id}'>Назад</a>"
        return HTMLResponse(body, status_code=400)

    try:
        await conn.execute(
            """
            INSERT INTO schedule_template
                (semester_id, group_id, day_of_week, pair_number, week_parity,
                 lesson_id, teacher_id, room_id, is_online, online_link)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            semester_id, group_id, day_of_week, pair_number, week_parity,
            lesson_id, teacher_id, room_id, is_online, online_link,
        )
    except asyncpg.exceptions.UniqueViolationError:
        return HTMLResponse(
            "<h1>Ошибка</h1><p>В этом слоте уже есть запись шаблона "
            "(группа+день+пара+чётность+семестр должны быть уникальны).</p>"
            f"<a href='/schedule/templates?group_id={group_id}'>Назад</a>",
            status_code=400,
        )
    return RedirectResponse(
        url=f"/schedule/templates?group_id={group_id}", status_code=303,
    )


@router.get("/templates/edit/{template_id}")
async def edit_template_form(
    request: Request,
    template_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    template = await conn.fetchrow(
        "SELECT * FROM schedule_template WHERE template_id = $1", template_id,
    )
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    groups, semesters, teachers, lessons, rooms = await _load_form_data(conn)
    return templates.TemplateResponse(
        "schedule/template_form.html",
        {
            "request": request, "template": template,
            "groups": groups, "semesters": semesters,
            "teachers": teachers, "lessons": lessons, "rooms": rooms,
        },
    )


@router.post("/templates/edit/{template_id}")
async def edit_template_submit(
    template_id: int,
    semester_id: int = Form(...),
    group_id: int = Form(...),
    day_of_week: int = Form(...),
    pair_number: int = Form(...),
    week_parity: str = Form("all"),
    lesson_id: int = Form(...),
    teacher_id: int = Form(...),
    room_id: int = Form(None),
    is_online: bool = Form(False),
    online_link: str = Form(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    if is_online:
        room_id = None

    errors = await _validate_constraints(
        conn,
        semester_id=semester_id,
        group_id=group_id,
        day_of_week=day_of_week,
        pair_number=pair_number,
        week_parity=week_parity,
        lesson_id=lesson_id,
        teacher_id=teacher_id,
        room_id=room_id,
        is_online=is_online,
        exclude_template_id=template_id,
    )
    if errors:
        body = "<h1>Ошибки при редактировании шаблона</h1><ul>"
        for e in errors:
            body += f"<li>{e}</li>"
        body += "</ul>"
        body += f"<a href='/schedule/templates?group_id={group_id}'>Назад</a>"
        return HTMLResponse(body, status_code=400)

    await conn.execute(
        """
        UPDATE schedule_template
           SET semester_id  = $1, group_id = $2, day_of_week = $3,
               pair_number  = $4, week_parity = $5, lesson_id  = $6,
               teacher_id   = $7, room_id    = $8, is_online  = $9,
               online_link  = $10
         WHERE template_id  = $11
        """,
        semester_id, group_id, day_of_week, pair_number, week_parity,
        lesson_id, teacher_id, room_id, is_online, online_link, template_id,
    )
    return RedirectResponse(
        url=f"/schedule/templates?group_id={group_id}", status_code=303,
    )


@router.post("/templates/delete/{template_id}")
async def delete_template(
    template_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    row = await conn.fetchrow(
        "SELECT group_id FROM schedule_template WHERE template_id = $1", template_id,
    )
    await conn.execute(
        "DELETE FROM schedule_template WHERE template_id = $1", template_id,
    )
    if row:
        return RedirectResponse(
            url=f"/schedule/templates?group_id={row['group_id']}", status_code=303,
        )
    return RedirectResponse(url="/schedule/templates", status_code=303)


# ===================== EXCEPTIONS CRUD =====================

@router.get("/exceptions")
async def list_exceptions(
    request: Request,
    group_id: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    conn=Depends(get_conn),
):
    group_id = _opt_int(group_id)
    groups = await conn.fetch("SELECT group_id, name FROM study_group ORDER BY name")

    today = date.today()
    if not date_from:
        date_from = (today - timedelta(days=14)).isoformat()
    if not date_to:
        date_to = (today + timedelta(days=14)).isoformat()
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)

    base_query = """
        SELECT e.*,
               st.day_of_week AS tpl_day, st.pair_number AS tpl_pair,
               st.week_parity AS tpl_parity,
               sg_template.name AS template_group_name,
               sg_explicit.name AS explicit_group_name,
               cs_tpl.name AS tpl_subject_name,
               cs_exc.name AS exc_subject_name
          FROM schedule_exception e
          LEFT JOIN schedule_template st ON e.template_id = st.template_id
          LEFT JOIN study_group sg_template ON st.group_id = sg_template.group_id
          LEFT JOIN study_group sg_explicit ON e.group_id = sg_explicit.group_id
          LEFT JOIN lesson l_tpl ON st.lesson_id = l_tpl.lesson_id
          LEFT JOIN curriculum_subject cs_tpl ON l_tpl.subject_id = cs_tpl.subject_id
          LEFT JOIN lesson l_exc ON e.lesson_id = l_exc.lesson_id
          LEFT JOIN curriculum_subject cs_exc ON l_exc.subject_id = cs_exc.subject_id
         WHERE e.entry_date BETWEEN $1 AND $2
    """
    args = [d_from, d_to]
    if group_id:
        base_query += " AND (st.group_id = $3 OR e.group_id = $3)"
        args.append(group_id)
    base_query += " ORDER BY e.entry_date, st.day_of_week, st.pair_number, e.entry_date"

    rows = await conn.fetch(base_query, *args)

    return templates.TemplateResponse(
        "schedule/exceptions_list.html",
        {
            "request": request,
            "groups": groups,
            "group_id": group_id,
            "date_from": date_from,
            "date_to": date_to,
            "exceptions": rows,
        },
    )


async def _load_exception_form_data(conn):
    templates_list = await conn.fetch(
        """
        SELECT st.template_id, st.day_of_week, st.pair_number, st.week_parity,
               sg.name AS group_name,
               cs.name AS subject_name,
               tch.last_name || ' ' || tch.first_name AS teacher_name
          FROM schedule_template st
          JOIN study_group sg ON st.group_id = sg.group_id
          JOIN lesson l ON st.lesson_id = l.lesson_id
          JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
          JOIN teacher tch ON st.teacher_id = tch.teacher_id
         ORDER BY sg.name, st.day_of_week, st.pair_number
        """,
    )
    teachers = await conn.fetch(
        "SELECT teacher_id, last_name || ' ' || first_name AS full_name FROM teacher ORDER BY last_name"
    )
    lessons = await conn.fetch(
        """
        SELECT l.lesson_id, cs.name AS subject_name, l.lesson_type, l.duration_minutes
          FROM lesson l
          JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
         ORDER BY cs.name, l.lesson_type
        """,
    )
    rooms = await conn.fetch(
        "SELECT room_id, name || ' (' || room_type || ', ' || capacity || ' чел)' AS label FROM room ORDER BY name"
    )
    groups = await conn.fetch("SELECT group_id, name FROM study_group ORDER BY name")
    return templates_list, teachers, lessons, rooms, groups


def _opt_int(val):
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_qs_int(value: str = Query("")):
    return _opt_int(value)


@router.get("/exceptions/add")
async def add_exception_form(
    request: Request,
    template_id: str = Query(""),
    group_id: str = Query(""),
    entry_date: str = Query(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    templates_list, teachers, lessons, rooms, groups = await _load_exception_form_data(conn)
    return templates.TemplateResponse(
        "schedule/exception_form.html",
        {
            "request": request, "exception": None,
            "templates_list": templates_list,
            "teachers": teachers, "lessons": lessons, "rooms": rooms, "groups": groups,
            "preselected_template": _opt_int(template_id),
            "preselected_group": _opt_int(group_id),
            "preselected_date": entry_date or None,
        },
    )


@router.post("/exceptions/add")
async def add_exception_submit(
    exception_type: str = Form(...),
    template_id: str = Form(""),
    group_id: str = Form(""),
    day_of_week: str = Form(""),
    pair_number: str = Form(""),
    week_parity: str = Form("all"),
    entry_date: str = Form(...),
    lesson_id: str = Form(""),
    teacher_id: str = Form(""),
    room_id: str = Form(""),
    is_online: str = Form(""),
    online_link: str = Form(""),
    note: str = Form(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    template_id_val = _opt_int(template_id)
    group_id_val = _opt_int(group_id)
    day_of_week_val = _opt_int(day_of_week)
    pair_number_val = _opt_int(pair_number)
    lesson_id_val = _opt_int(lesson_id)
    teacher_id_val = _opt_int(teacher_id)
    room_id_val = _opt_int(room_id)
    is_online_val = (is_online == "true") if is_online else None
    week_parity_val = week_parity if week_parity else None

    if exception_type in ("replace", "cancel") and not template_id_val:
        return HTMLResponse(
            "<h1>Ошибка</h1><p>Для replace/cancel необходимо выбрать шаблон.</p>"
            "<a href='/schedule/exceptions'>Назад</a>",
            status_code=400,
        )

    # Дополнительная валидация для типа 'add'
    if exception_type == "add":
        if not (group_id_val and day_of_week_val and pair_number_val
                and lesson_id_val and teacher_id_val):
            return HTMLResponse(
                "<h1>Ошибка</h1><p>Для типа add нужно заполнить группу, "
                "день, пару, занятие и преподавателя.</p>"
                "<a href='/schedule/exceptions'>Назад</a>",
                status_code=400,
            )
        # Нужен semester_id для валидации — берём из семестра группы
        sem_id = await conn.fetchval(
            "SELECT semester_id FROM study_group WHERE group_id = $1",
            group_id_val,
        )
        if not sem_id:
            return HTMLResponse(
                "<h1>Ошибка</h1><p>Не найден семестр для выбранной группы.</p>"
                "<a href='/schedule/exceptions'>Назад</a>",
                status_code=400,
            )
        if is_online_val:
            room_id_val_for_check = None
        else:
            room_id_val_for_check = room_id_val
        errors = await _validate_constraints(
            conn,
            semester_id=sem_id,
            group_id=group_id_val,
            day_of_week=day_of_week_val,
            pair_number=pair_number_val,
            week_parity=week_parity_val or "all",
            lesson_id=lesson_id_val,
            teacher_id=teacher_id_val,
            room_id=room_id_val_for_check,
            is_online=bool(is_online_val),
            exception_entry_date=date.fromisoformat(entry_date),
            is_exception_add=True,
        )
        if errors:
            body = "<h1>Ошибки при создании исключения</h1><ul>"
            for e in errors:
                body += f"<li>{e}</li>"
            body += "</ul><a href='/schedule/exceptions'>Назад</a>"
            return HTMLResponse(body, status_code=400)
    elif exception_type == "replace":
        # Для replace: если заданы teacher_id/room_id, проверим пересечения
        # на конкретную дату (с учётом чётности шаблона).
        tpl = await conn.fetchrow(
            "SELECT * FROM schedule_template WHERE template_id = $1",
            template_id_val,
        )
        if tpl:
            d = date.fromisoformat(entry_date)
            dow = d.weekday() + 1
            is_even = d.isocalendar()[1] % 2 == 0
            if not _parity_matches(tpl["week_parity"], is_even):
                return HTMLResponse(
                    "<h1>Ошибка</h1><p>Нельзя заменить пару на дату, "
                    "не совпадающую с чётностью шаблона.</p>"
                    "<a href='/schedule/exceptions'>Назад</a>",
                    status_code=400,
                )
            new_teacher = teacher_id_val or tpl["teacher_id"]
            new_room = room_id_val if room_id_val is not None else tpl["room_id"]
            if teacher_id_val:
                tbusy = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM schedule_template st
                     WHERE st.teacher_id = $1 AND st.day_of_week = $2
                       AND st.pair_number = $3 AND st.template_id <> $4
                       AND (st.week_parity = 'all'
                            OR (st.week_parity = 'even' AND $5)
                            OR (st.week_parity = 'odd'  AND NOT $5))
                    """,
                    new_teacher, dow, tpl["pair_number"],
                    template_id_val, is_even,
                )
                if tbusy and tbusy > 0:
                    return HTMLResponse(
                        "<h1>Ошибка</h1><p>Новый преподаватель занят в "
                        "этот день и пару по другому шаблону.</p>"
                        "<a href='/schedule/exceptions'>Назад</a>",
                        status_code=400,
                    )
            if room_id_val is not None and not is_online_val:
                rbusy = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM schedule_template st
                     WHERE st.room_id = $1 AND st.day_of_week = $2
                       AND st.pair_number = $3 AND st.template_id <> $4
                       AND (st.week_parity = 'all'
                            OR (st.week_parity = 'even' AND $5)
                            OR (st.week_parity = 'odd'  AND NOT $5))
                    """,
                    new_room, dow, tpl["pair_number"],
                    template_id_val, is_even,
                )
                if rbusy and rbusy > 0:
                    return HTMLResponse(
                        "<h1>Ошибка</h1><p>Новая аудитория занята в "
                        "этот день и пару по другому шаблону.</p>"
                        "<a href='/schedule/exceptions'>Назад</a>",
                        status_code=400,
                    )

    try:
        await conn.execute(
            """
            INSERT INTO schedule_exception
                (exception_type, template_id, group_id, day_of_week, pair_number,
                 week_parity, entry_date, lesson_id, teacher_id, room_id,
                 is_online, online_link, note)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            exception_type, template_id_val, group_id_val, day_of_week_val,
            pair_number_val, week_parity_val, date.fromisoformat(entry_date),
            lesson_id_val, teacher_id_val, room_id_val, is_online_val,
            online_link, note,
        )
    except Exception as e:
        return HTMLResponse(
            f"<h1>Ошибка</h1><p>{e}</p>"
            f"<a href='/schedule/exceptions'>Назад</a>",
            status_code=400,
        )

    redirect_group = group_id_val
    if exception_type in ("replace", "cancel") and template_id_val:
        row = await conn.fetchrow(
            "SELECT group_id FROM schedule_template WHERE template_id = $1",
            template_id_val,
        )
        if row:
            redirect_group = row["group_id"]

    if redirect_group:
        return RedirectResponse(
            url=f"/schedule/exceptions?group_id={redirect_group}", status_code=303,
        )
    return RedirectResponse(url="/schedule/exceptions", status_code=303)


@router.get("/exceptions/edit/{exception_id}")
async def edit_exception_form(
    request: Request,
    exception_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    exc = await conn.fetchrow(
        "SELECT * FROM schedule_exception WHERE exception_id = $1", exception_id,
    )
    if not exc:
        raise HTTPException(status_code=404, detail="Исключение не найдено")
    templates_list, teachers, lessons, rooms, groups = await _load_exception_form_data(conn)
    return templates.TemplateResponse(
        "schedule/exception_form.html",
        {
            "request": request, "exception": exc,
            "templates_list": templates_list,
            "teachers": teachers, "lessons": lessons, "rooms": rooms, "groups": groups,
        },
    )


@router.post("/exceptions/edit/{exception_id}")
async def edit_exception_submit(
    exception_id: int,
    exception_type: str = Form(...),
    template_id: str = Form(""),
    group_id: str = Form(""),
    day_of_week: str = Form(""),
    pair_number: str = Form(""),
    week_parity: str = Form("all"),
    entry_date: str = Form(...),
    lesson_id: str = Form(""),
    teacher_id: str = Form(""),
    room_id: str = Form(""),
    is_online: str = Form(""),
    online_link: str = Form(""),
    note: str = Form(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    template_id_val = _opt_int(template_id)
    group_id_val = _opt_int(group_id)
    day_of_week_val = _opt_int(day_of_week)
    pair_number_val = _opt_int(pair_number)
    lesson_id_val = _opt_int(lesson_id)
    teacher_id_val = _opt_int(teacher_id)
    room_id_val = _opt_int(room_id)
    is_online_val = (is_online == "true") if is_online else None

    if exception_type == "add":
        if not (group_id_val and day_of_week_val and pair_number_val
                and lesson_id_val and teacher_id_val):
            return HTMLResponse(
                "<h1>Ошибка</h1><p>Для типа add нужно заполнить группу, "
                "день, пару, занятие и преподавателя.</p>"
                "<a href='/schedule/exceptions'>Назад</a>",
                status_code=400,
            )
        sem_id = await conn.fetchval(
            "SELECT semester_id FROM study_group WHERE group_id = $1",
            group_id_val,
        )
        if not sem_id:
            return HTMLResponse(
                "<h1>Ошибка</h1><p>Не найден семестр для выбранной группы.</p>"
                "<a href='/schedule/exceptions'>Назад</a>",
                status_code=400,
            )
        room_for_check = None if is_online_val else room_id_val
        errors = await _validate_constraints(
            conn,
            semester_id=sem_id,
            group_id=group_id_val,
            day_of_week=day_of_week_val,
            pair_number=pair_number_val,
            week_parity=week_parity or "all",
            lesson_id=lesson_id_val,
            teacher_id=teacher_id_val,
            room_id=room_for_check,
            is_online=bool(is_online_val),
            exception_entry_date=date.fromisoformat(entry_date),
            is_exception_add=True,
            exclude_template_id=exception_id,
        )
        if errors:
            body = "<h1>Ошибки при редактировании исключения</h1><ul>"
            for e in errors:
                body += f"<li>{e}</li>"
            body += "</ul><a href='/schedule/exceptions'>Назад</a>"
            return HTMLResponse(body, status_code=400)

    await conn.execute(
        """
        UPDATE schedule_exception
           SET exception_type = $1, template_id = $2, group_id    = $3,
               day_of_week    = $4, pair_number = $5, week_parity = $6,
               entry_date     = $7, lesson_id   = $8, teacher_id  = $9,
               room_id        = $10, is_online   = $11, online_link= $12,
               note           = $13
         WHERE exception_id   = $14
        """,
        exception_type, template_id_val, group_id_val, day_of_week_val,
        pair_number_val, week_parity, date.fromisoformat(entry_date),
        lesson_id_val, teacher_id_val, room_id_val, is_online_val,
        online_link, note, exception_id,
    )
    return RedirectResponse(url="/schedule/exceptions", status_code=303)


@router.post("/exceptions/delete/{exception_id}")
async def delete_exception(
    exception_id: int,
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    await conn.execute(
        "DELETE FROM schedule_exception WHERE exception_id = $1", exception_id,
    )
    return RedirectResponse(url="/schedule/exceptions", status_code=303)


# ===================== COPY =====================

@router.get("/copy")
async def copy_form(
    request: Request,
    from_group_id: str = Query(""),
    to_group_id: str = Query(""),
    from_semester_id: str = Query(""),
    to_semester_id: str = Query(""),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    groups, semesters, _, _, _ = await _load_form_data(conn)
    return templates.TemplateResponse(
        "schedule/copy.html",
        {
            "request": request,
            "groups": groups, "semesters": semesters,
            "from_group_id": _opt_int(from_group_id),
            "to_group_id": _opt_int(to_group_id),
            "from_semester_id": _opt_int(from_semester_id),
            "to_semester_id": _opt_int(to_semester_id),
        },
    )


@router.post("/copy")
async def copy_submit(
    from_group_id: int = Form(...),
    from_semester_id: int = Form(...),
    to_group_id: int = Form(...),
    to_semester_id: int = Form(...),
    conn=Depends(get_conn),
    user=Depends(require_teacher),
):
    try:
        await conn.execute(
            """
            INSERT INTO schedule_template
                (semester_id, group_id, day_of_week, pair_number, week_parity,
                 lesson_id, teacher_id, room_id, is_online, online_link)
            SELECT $1, $2, day_of_week, pair_number, week_parity,
                   lesson_id, teacher_id, room_id, is_online, online_link
              FROM schedule_template
             WHERE group_id = $3 AND semester_id = $4
            ON CONFLICT (semester_id, group_id, day_of_week, pair_number, week_parity)
            DO NOTHING
            """,
            to_semester_id, to_group_id, from_group_id, from_semester_id,
        )
    except Exception as e:
        return HTMLResponse(
            f"<h1>Ошибка копирования</h1><p>{e}</p>"
            f"<a href='/schedule/copy'>Назад</a>",
            status_code=400,
        )
    return RedirectResponse(
        url=f"/schedule/templates?group_id={to_group_id}", status_code=303,
    )
