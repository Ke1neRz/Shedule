-- ============================================================
-- Часть 1: Схема БД
-- ============================================================
-- Полная схема (DDL + триггеры + seed) хранится в init_db.sql.
-- Здесь приведены только определения таблиц, участвующих в
-- запросах расписания, для удобства чтения.
--
-- Ключевые изменения относительно «классической» схемы:
--   * curriculum разделён на curriculum (план на 4 года) +
--     curriculum_semester (по семестрам, weeks=18).
--   * Расписание — это пара:
--       schedule_template  — регулярный шаблон семестра
--                            (день недели + номер пары + чётность)
--       schedule_exception — разовые изменения на конкретную дату
--                            (replace / cancel / add)
--   * Время пар хранится в справочнике timeslot (для шаблонов
--     пар не привязаны ко времени, чтобы поддержать разные вузы).
-- ============================================================


-- ============================================================
-- Часть 2: Запросы (15 шт.)
-- ============================================================
-- В запросах ниже используются переменные подстановки psql:
--   :date_from   'YYYY-MM-DD'   — начало диапазона
--   :date_to     'YYYY-MM-DD'   — конец диапазона
--   :group_ids   '{1,2,3}'      — массив group_id
--   :division_id 1              — id подразделения
--   :semester_id 1              — id семестра
--   :semester_start / :semester_end — даты семестра
--   :week_offset 1              — сдвиг в неделях для копирования
-- ============================================================


-- ============================================================
-- 0. Вспомогательный CTE: материализованное расписание
--    Соединяет schedule_template с датами диапазона, применяет
--    schedule_exception (cancel убирает, replace перекрывает
--    поля, add добавляет разовые занятия).
-- ============================================================
-- Использование: подставить в FROM каждого запроса ниже.
--
-- WITH RECURSIVE dates(d) AS (
--     SELECT DATE :'date_from'::TEXT
--     UNION ALL
--     SELECT d + INTERVAL '1 day' FROM dates WHERE d < DATE :'date_to'::TEXT
-- ),
-- cal AS (
--     SELECT d, EXTRACT(ISODOW FROM d)::INT AS dow,
--            (EXTRACT(WEEK FROM d)::INT % 2 = 0) AS is_even
--     FROM dates
-- ),
-- tpl AS (
--     SELECT st.*, cal.d
--       FROM schedule_template st
--       JOIN cal ON st.day_of_week = cal.dow
--      WHERE st.group_id = ANY(:'group_ids'::INT[])
--        AND (st.week_parity = 'all'
--             OR (st.week_parity = 'even' AND cal.is_even)
--             OR (st.week_parity = 'odd'  AND NOT cal.is_even))
-- ),
-- cancels AS (
--     SELECT template_id, entry_date FROM schedule_exception
--      WHERE exception_type = 'cancel'
--        AND entry_date BETWEEN DATE :'date_from'::TEXT AND DATE :'date_to'::TEXT
-- ),
-- replaces AS (
--     SELECT * FROM schedule_exception
--      WHERE exception_type = 'replace'
--        AND entry_date BETWEEN DATE :'date_from'::TEXT AND DATE :'date_to'::TEXT
-- ),
-- adds AS (
--     SELECT entry_date AS d, group_id, day_of_week, pair_number, week_parity,
--            lesson_id, teacher_id, room_id,
--            COALESCE(is_online, FALSE) AS is_online,
--            online_link, note
--       FROM schedule_exception
--      WHERE exception_type = 'add'
--        AND entry_date BETWEEN DATE :'date_from'::TEXT AND DATE :'date_to'::TEXT
--        AND group_id = ANY(:'group_ids'::INT[])
-- ),
-- mat AS (
--     SELECT t.d, t.group_id, t.day_of_week, t.pair_number, t.week_parity,
--            COALESCE(r.lesson_id,  t.lesson_id)  AS lesson_id,
--            COALESCE(r.teacher_id, t.teacher_id) AS teacher_id,
--            COALESCE(r.room_id,    t.room_id)    AS room_id,
--            COALESCE(r.is_online,  t.is_online)  AS is_online,
--            COALESCE(r.online_link,t.online_link)AS online_link
--       FROM tpl t
--       LEFT JOIN replaces r ON r.template_id = t.template_id AND r.entry_date = t.d
--      WHERE NOT EXISTS (SELECT 1 FROM cancels c
--                        WHERE c.template_id = t.template_id AND c.entry_date = t.d)
--     UNION ALL
--     SELECT d, group_id, day_of_week, pair_number, week_parity,
--            lesson_id, teacher_id, room_id, is_online, online_link
--       FROM adds
-- )
-- SELECT * FROM mat;


-- 1. Расписание одной учебной группы (на диапазон дат)
WITH RECURSIVE dates(d) AS (
    SELECT DATE :'date_from'::TEXT
    UNION ALL
    SELECT d + INTERVAL '1 day' FROM dates WHERE d < DATE :'date_to'::TEXT
),
cal AS (
    SELECT d, EXTRACT(ISODOW FROM d)::INT AS dow,
           (EXTRACT(WEEK FROM d)::INT % 2 = 0) AS is_even
      FROM dates
),
cancels AS (
    SELECT template_id, entry_date FROM schedule_exception
     WHERE exception_type = 'cancel'
       AND entry_date BETWEEN DATE :'date_from'::TEXT AND DATE :'date_to'::TEXT
),
replaces AS (
    SELECT * FROM schedule_exception
     WHERE exception_type = 'replace'
       AND entry_date BETWEEN DATE :'date_from'::TEXT AND DATE :'date_to'::TEXT
),
mat AS (
    SELECT st.*, cal.d,
           COALESCE(r.lesson_id,  st.lesson_id)  AS eff_lesson_id,
           COALESCE(r.teacher_id, st.teacher_id) AS eff_teacher_id,
           COALESCE(r.room_id,    st.room_id)    AS eff_room_id,
           COALESCE(r.is_online,  st.is_online)  AS eff_is_online
      FROM schedule_template st
      JOIN cal ON st.day_of_week = cal.dow
      LEFT JOIN replaces r ON r.template_id = st.template_id AND r.entry_date = cal.d
     WHERE st.group_id = 1
       AND (st.week_parity = 'all'
            OR (st.week_parity = 'even' AND cal.is_even)
            OR (st.week_parity = 'odd'  AND NOT cal.is_even))
       AND NOT EXISTS (SELECT 1 FROM cancels c
                       WHERE c.template_id = st.template_id AND c.entry_date = cal.d)
)
SELECT
    m.d                AS entry_date,
    m.day_of_week,
    m.pair_number,
    cs.name            AS subject,
    l.lesson_type,
    tch.last_name || ' ' || LEFT(tch.first_name,1) || '.'
        || COALESCE(LEFT(tch.middle_name,1),'') || '.' AS teacher,
    CASE WHEN m.eff_is_online THEN 'Онлайн' ELSE r.name END AS room,
    b.name             AS building
FROM mat m
JOIN lesson l              ON m.eff_lesson_id  = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id     = cs.subject_id
JOIN teacher tch           ON m.eff_teacher_id = tch.teacher_id
LEFT JOIN room r           ON m.eff_room_id    = r.room_id
LEFT JOIN building b       ON r.building_id    = b.building_id
ORDER BY m.d, m.pair_number;


-- 2. Шахматная ведомость (расписание нескольких групп на диапазон)
SELECT
    m.day_of_week,
    m.pair_number,
    sg.name            AS group_name,
    cs.name            AS subject,
    l.lesson_type,
    tch.last_name      AS teacher,
    CASE WHEN m.is_online THEN 'Онлайн' ELSE r.name END AS room
FROM ( ... CTE mat ... ) m     -- заменить на CTE из блока 0
JOIN study_group sg    ON m.group_id  = sg.group_id
JOIN lesson l          ON m.lesson_id = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN teacher tch       ON m.teacher_id = tch.teacher_id
LEFT JOIN room r       ON m.room_id    = r.room_id
ORDER BY m.day_of_week, m.pair_number, sg.name;


-- 3. Расписание консультаций, зачётов и экзаменов
SELECT
    sg.name            AS group_name,
    cs.name            AS subject,
    l.lesson_type,
    m.d                AS entry_date,
    tch.last_name || ' ' || LEFT(tch.first_name,1) || '.' AS teacher,
    CASE WHEN m.is_online THEN 'Онлайн' ELSE r.name END AS room,
    b.name             AS building
FROM ( ... CTE mat ... ) m
JOIN study_group sg    ON m.group_id   = sg.group_id
JOIN lesson l          ON m.lesson_id  = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN teacher tch       ON m.teacher_id = tch.teacher_id
LEFT JOIN room r       ON m.room_id    = r.room_id
LEFT JOIN building b   ON r.building_id = b.building_id
WHERE l.lesson_type IN ('exam', 'pass_test', 'consult')
ORDER BY m.d, m.pair_number;


-- 4. План занятости преподавателей одного подразделения
SELECT
    tch.last_name || ' ' || tch.first_name AS teacher,
    m.day_of_week,
    m.pair_number,
    cs.name            AS subject,
    l.lesson_type,
    sg.name            AS study_group,
    CASE WHEN m.is_online THEN 'Онлайн' ELSE r.name END AS room
FROM ( ... CTE mat ... ) m
JOIN teacher tch            ON m.teacher_id = tch.teacher_id
JOIN lesson l               ON m.lesson_id  = l.lesson_id
JOIN curriculum_subject cs  ON l.subject_id = cs.subject_id
JOIN study_group sg         ON m.group_id   = sg.group_id
LEFT JOIN room r            ON m.room_id    = r.room_id
WHERE tch.division_id = :division_id
ORDER BY tch.last_name, m.day_of_week, m.pair_number;


-- 5. Сводная загрузка учебных помещений
WITH RECURSIVE dates(d) AS (
    SELECT DATE :'date_from'::TEXT
    UNION ALL
    SELECT d + INTERVAL '1 day' FROM dates WHERE d < DATE :'date_to'::TEXT
),
slots AS (
    SELECT DISTINCT day_of_week, pair_number FROM schedule_template
)
SELECT
    b.name             AS building,
    r.room_type,
    r.name             AS room,
    s.day_of_week,
    s.pair_number,
    COUNT(DISTINCT st.template_id) AS sessions_count,
    ROUND(COUNT(DISTINCT st.template_id) * 100.0 /
          GREATEST((SELECT COUNT(*) FROM dates), 1), 2) AS load_pct
FROM room r
JOIN building b   ON r.building_id = b.building_id
CROSS JOIN slots s
LEFT JOIN schedule_template st
       ON st.room_id     = r.room_id
      AND st.day_of_week  = s.day_of_week
      AND st.pair_number  = s.pair_number
GROUP BY b.name, r.room_type, r.name, s.day_of_week, s.pair_number
ORDER BY b.name, r.room_type, r.name, s.day_of_week, s.pair_number;


-- 6. Проверка пересечений в расписании группы
SELECT
    sg.name            AS group_name,
    m.day_of_week,
    m.pair_number,
    m.d                AS entry_date,
    COUNT(*)           AS overlaps
FROM ( ... CTE mat ... ) m
JOIN study_group sg ON m.group_id = sg.group_id
GROUP BY sg.name, m.day_of_week, m.pair_number, m.d
HAVING COUNT(*) > 1;


-- 7. Проверка: лаборатории только в аудиториях нужного типа
SELECT
    st.template_id,
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
  AND r.room_type NOT IN ('lab', 'computer');


-- 8. Проверка вместимости помещения для группы
SELECT
    st.template_id,
    sg.name            AS group_name,
    sg.student_count,
    r.name             AS room,
    r.capacity
FROM schedule_template st
JOIN study_group sg ON st.group_id = sg.group_id
JOIN room r         ON st.room_id  = r.room_id
WHERE sg.student_count > r.capacity;


-- 9. Проверка: преподаватель не более 5 пар в день (по шаблону за семестр)
--    (с учётом чётности: макс. ~9 пар в 2-недельном цикле, поэтому
--     строгая проверка делается на материализованном расписании — CTE mat)
SELECT
    tch.last_name || ' ' || tch.first_name AS teacher,
    m.d                AS entry_date,
    COUNT(*)           AS pairs_per_day
FROM ( ... CTE mat ... ) m
JOIN teacher tch ON m.teacher_id = tch.teacher_id
GROUP BY tch.teacher_id, tch.last_name, tch.first_name, m.d
HAVING COUNT(*) > 5
ORDER BY teacher, entry_date;


-- 10. Проверка: группа не более 5 пар в день
SELECT
    sg.name            AS group_name,
    m.d                AS entry_date,
    COUNT(*)           AS pairs_per_day
FROM ( ... CTE mat ... ) m
JOIN study_group sg ON m.group_id = sg.group_id
GROUP BY sg.group_id, sg.name, m.d
HAVING COUNT(*) > 5
ORDER BY group_name, entry_date;


-- 11. Копирование шаблона расписания на следующий семестр
INSERT INTO schedule_template
    (semester_id, group_id, day_of_week, pair_number, week_parity,
     lesson_id, teacher_id, room_id, is_online, online_link)
SELECT
    :new_semester_id,         -- id целевого семестра
    group_id,
    day_of_week,
    pair_number,
    week_parity,
    lesson_id,
    teacher_id,
    room_id,
    is_online,
    online_link
FROM schedule_template
WHERE group_id    = :from_group_id
  AND semester_id = :from_semester_id
ON CONFLICT (semester_id, group_id, day_of_week, pair_number, week_parity)
DO NOTHING;


-- 12. Список подразделений с иерархией
WITH RECURSIVE div_tree AS (
    SELECT division_id, name, parent_id, 0 AS level, name::TEXT AS path
      FROM division
     WHERE parent_id IS NULL
    UNION ALL
    SELECT d.division_id, d.name, d.parent_id, dt.level + 1,
           dt.path || ' → ' || d.name
      FROM division d
      JOIN div_tree dt ON d.parent_id = dt.division_id
)
SELECT
    REPEAT('  ', level) || name AS division_name,
    level,
    path
FROM div_tree
ORDER BY path;


-- 13. Нагрузка преподавателя за семестр
WITH RECURSIVE dates(d) AS (
    SELECT :semester_start::DATE
    UNION ALL
    SELECT d + INTERVAL '1 day' FROM dates WHERE d < :semester_end::DATE
),
cal AS (
    SELECT d, EXTRACT(ISODOW FROM d)::INT AS dow,
           (EXTRACT(WEEK FROM d)::INT % 2 = 0) AS is_even
      FROM dates
),
cancels AS (
    SELECT template_id, entry_date FROM schedule_exception
     WHERE exception_type = 'cancel'
       AND entry_date BETWEEN :semester_start AND :semester_end
),
replaces AS (
    SELECT * FROM schedule_exception
     WHERE exception_type = 'replace'
       AND entry_date BETWEEN :semester_start AND :semester_end
),
mat AS (
    SELECT st.template_id, st.teacher_id, st.lesson_id, st.pair_number,
           COALESCE(r.lesson_id, st.lesson_id)  AS eff_lesson_id,
           COALESCE(r.teacher_id, st.teacher_id) AS eff_teacher_id
      FROM schedule_template st
      JOIN curriculum_semester sm ON st.semester_id = sm.semester_id
      JOIN cal ON st.day_of_week = cal.dow
      LEFT JOIN replaces r ON r.template_id = st.template_id AND r.entry_date = cal.d
     WHERE sm.semester_id = :semester_id
       AND (st.week_parity = 'all'
            OR (st.week_parity = 'even' AND cal.is_even)
            OR (st.week_parity = 'odd'  AND NOT cal.is_even))
       AND NOT EXISTS (SELECT 1 FROM cancels c
                       WHERE c.template_id = st.template_id AND c.entry_date = cal.d)
)
SELECT
    tch.last_name || ' ' || tch.first_name AS teacher,
    l.lesson_type,
    COUNT(*)               AS sessions,
    SUM(l.duration_minutes) AS total_minutes,
    ROUND(SUM(l.duration_minutes)::NUMERIC / 45, 2) AS academic_hours
FROM mat m
JOIN teacher tch  ON m.eff_teacher_id = tch.teacher_id
JOIN lesson l     ON m.eff_lesson_id  = l.lesson_id
GROUP BY tch.teacher_id, tch.last_name, tch.first_name, l.lesson_type
ORDER BY teacher, l.lesson_type;


-- 14. Дисциплины учебного плана для семестра
SELECT
    cs.subject_id,
    cs.name          AS subject,
    cs.lecture_hours,
    cs.practice_hours,
    cs.lab_hours,
    cs.assessment_type,
    sm.weeks,
    ROUND(cs.lecture_hours::NUMERIC  / sm.weeks, 2) AS lectures_per_week,
    ROUND(cs.practice_hours::NUMERIC / sm.weeks, 2) AS practice_per_week,
    ROUND(cs.lab_hours::NUMERIC      / sm.weeks, 2) AS labs_per_week
FROM curriculum_subject cs
JOIN curriculum_semester sm ON cs.semester_id = sm.semester_id
WHERE sm.semester_id = :semester_id
ORDER BY cs.name;


-- 15. Расчёт длительности зачёта/экзамена для группы
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
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN study_group sg        ON sg.semester_id = cs.semester_id
WHERE l.lesson_type IN ('exam', 'pass_test')
ORDER BY sg.name, cs.name;
