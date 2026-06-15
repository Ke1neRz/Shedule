-- Часть 1: Структура таблиц (DDL)

-- Университет
CREATE TABLE university (
    university_id   SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    address         VARCHAR(300)
);

-- Подразделения (иерархия)
CREATE TABLE division (
    division_id     SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    parent_id       INTEGER REFERENCES division(division_id),
    university_id   INTEGER NOT NULL REFERENCES university(university_id)
);

-- Преподаватели
CREATE TABLE teacher (
    teacher_id      SERIAL PRIMARY KEY,
    last_name       VARCHAR(100) NOT NULL,
    first_name      VARCHAR(100) NOT NULL,
    middle_name     VARCHAR(100),
    division_id     INTEGER NOT NULL REFERENCES division(division_id)
);

-- Учебные планы
CREATE TABLE curriculum (
    curriculum_id   SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    direction_code  VARCHAR(20),
    semester        SMALLINT NOT NULL,
    academic_year   SMALLINT NOT NULL,
    weeks           SMALLINT NOT NULL DEFAULT 18
);

-- Дисциплины учебного плана
CREATE TABLE curriculum_subject (
    subject_id      SERIAL PRIMARY KEY,
    curriculum_id   INTEGER NOT NULL REFERENCES curriculum(curriculum_id),
    name            VARCHAR(200) NOT NULL,
    lecture_hours   SMALLINT NOT NULL DEFAULT 0,
    practice_hours  SMALLINT NOT NULL DEFAULT 0,
    lab_hours       SMALLINT NOT NULL DEFAULT 0,
    assessment_type VARCHAR(10) NOT NULL CHECK (assessment_type IN ('exam', 'pass'))
);

-- Учебные занятия
CREATE TABLE lesson (
    lesson_id       SERIAL PRIMARY KEY,
    subject_id      INTEGER NOT NULL REFERENCES curriculum_subject(subject_id),
    lesson_type     VARCHAR(20) NOT NULL CHECK (lesson_type IN
                        ('lecture','practice','lab','exam','pass_test','consult')),
    duration_minutes SMALLINT NOT NULL
);

-- Связь преподавателя с занятиями
CREATE TABLE teacher_lesson (
    teacher_id  INTEGER NOT NULL REFERENCES teacher(teacher_id),
    lesson_id   INTEGER NOT NULL REFERENCES lesson(lesson_id),
    PRIMARY KEY (teacher_id, lesson_id)
);

-- Корпуса университета
CREATE TABLE building (
    building_id     SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    address         VARCHAR(300)
);

-- Время перемещения между корпусами (минуты)
CREATE TABLE building_distance (
    from_building_id INTEGER NOT NULL REFERENCES building(building_id),
    to_building_id   INTEGER NOT NULL REFERENCES building(building_id),
    distance_minutes SMALLINT NOT NULL,
    PRIMARY KEY (from_building_id, to_building_id),
    CHECK (from_building_id <> to_building_id)
);

-- Учебные помещения
CREATE TABLE room (
    room_id         SERIAL PRIMARY KEY,
    name            VARCHAR(20) NOT NULL UNIQUE,
    building_id     INTEGER NOT NULL REFERENCES building(building_id),
    room_type       VARCHAR(20) NOT NULL CHECK (room_type IN
                        ('lecture','practice','lab','computer')),
    capacity        SMALLINT NOT NULL CHECK (capacity > 0)
);

-- Учебные группы (подгруппы / потоки)
CREATE TABLE study_group (
    group_id        SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    student_count   SMALLINT NOT NULL CHECK (student_count > 0),
    curriculum_id   INTEGER NOT NULL REFERENCES curriculum(curriculum_id)
);

-- Справочник звонков (пары): 1=Пн..6=Сб
CREATE TABLE timeslot (
    timeslot_id     SERIAL PRIMARY KEY,
    day_of_week     SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 6),
    pair_number     SMALLINT NOT NULL CHECK (pair_number BETWEEN 1 AND 8),
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    UNIQUE (day_of_week, pair_number)
);

-- Наполнение справочника звонков
INSERT INTO timeslot (day_of_week, pair_number, start_time, end_time)
SELECT d, p, s::TIME, e::TIME
FROM (VALUES
  (1,'08:30','10:00'),(2,'10:10','11:40'),(3,'11:50','13:20'),
  (4,'13:30','15:00'),(5,'15:10','16:40'),(6,'16:50','18:20'),
  (7,'18:30','19:00'),(8,'19:10','20:40')
) slots(p,s,e)
CROSS JOIN generate_series(1,6) d;

-- Элемент расписания
CREATE TABLE schedule_entry (
    entry_id        SERIAL PRIMARY KEY,
    group_id        INTEGER NOT NULL REFERENCES study_group(group_id),
    lesson_id       INTEGER NOT NULL REFERENCES lesson(lesson_id),
    timeslot_id     INTEGER NOT NULL REFERENCES timeslot(timeslot_id),
    teacher_id      INTEGER NOT NULL REFERENCES teacher(teacher_id),
    room_id         INTEGER NOT NULL REFERENCES room(room_id),
    entry_date      DATE NOT NULL
);

-- Ограничения целостности

-- Помещение занято только одним занятием в один момент
CREATE UNIQUE INDEX uix_room_timeslot
    ON schedule_entry (room_id, timeslot_id, entry_date);

-- Преподаватель ведёт только одно занятие в один момент
CREATE UNIQUE INDEX uix_teacher_timeslot
    ON schedule_entry (teacher_id, timeslot_id, entry_date);

-- Группа имеет только одно занятие в один момент
CREATE UNIQUE INDEX uix_group_timeslot
    ON schedule_entry (group_id, timeslot_id, entry_date);


-- Часть 2: Запросы

-- 1. Расписание одной учебной группы
SELECT
    t.day_of_week,
    t.pair_number,
    t.start_time,
    t.end_time,
    s.entry_date,
    cs.name            AS subject,
    l.lesson_type,
    tch.last_name || ' ' || LEFT(tch.first_name,1) || '.' || LEFT(tch.middle_name,1) || '.' AS teacher,
    r.name             AS room,
    b.name             AS building
FROM schedule_entry s
JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
JOIN lesson l           ON s.lesson_id   = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
JOIN room r             ON s.room_id     = r.room_id
JOIN building b         ON r.building_id = b.building_id
WHERE s.group_id = :group_id    -- подставить нужный group_id
ORDER BY s.entry_date, t.pair_number;


-- 2. Шахматная ведомость (расписание нескольких групп)
SELECT
    t.day_of_week,
    t.pair_number,
    t.start_time,
    sg.name            AS group_name,
    cs.name            AS subject,
    l.lesson_type,
    tch.last_name      AS teacher,
    r.name             AS room
FROM schedule_entry s
JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
JOIN study_group sg     ON s.group_id    = sg.group_id
JOIN lesson l           ON s.lesson_id   = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
JOIN room r             ON s.room_id     = r.room_id
WHERE s.group_id = ANY(:group_ids)    -- массив нужных group_id
  AND s.entry_date BETWEEN :date_from AND :date_to
ORDER BY t.day_of_week, t.pair_number, sg.name;


-- 3. Расписание консультаций, зачётов и экзаменов
SELECT
    sg.name            AS group_name,
    cs.name            AS subject,
    l.lesson_type,
    s.entry_date,
    t.start_time,
    t.end_time,
    tch.last_name || ' ' || LEFT(tch.first_name,1) || '.' AS teacher,
    r.name             AS room,
    b.name             AS building
FROM schedule_entry s
JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
JOIN study_group sg     ON s.group_id    = sg.group_id
JOIN lesson l           ON s.lesson_id   = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
JOIN room r             ON s.room_id     = r.room_id
JOIN building b         ON r.building_id = b.building_id
WHERE s.group_id = ANY(:group_ids)
  AND l.lesson_type IN ('exam', 'pass_test', 'consult')
ORDER BY s.entry_date, t.start_time;


-- 4. План занятости преподавателей одного подразделения
SELECT
    tch.last_name || ' ' || tch.first_name AS teacher,
    t.day_of_week,
    t.pair_number,
    t.start_time,
    cs.name            AS subject,
    l.lesson_type,
    sg.name            AS study_group,
    r.name             AS room
FROM schedule_entry s
JOIN teacher tch        ON s.teacher_id  = tch.teacher_id
JOIN timeslot t         ON s.timeslot_id = t.timeslot_id
JOIN lesson l           ON s.lesson_id   = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN study_group sg     ON s.group_id    = sg.group_id
JOIN room r             ON s.room_id     = r.room_id
WHERE tch.division_id = :division_id
ORDER BY tch.last_name, t.day_of_week, t.pair_number;


-- 5. Сводная загрузка учебных помещений
SELECT
    b.name             AS building,
    r.room_type,
    r.name             AS room,
    t.day_of_week,
    t.pair_number,
    t.start_time,
    COUNT(s.entry_id)  AS sessions_count,
    ROUND(COUNT(s.entry_id) * 100.0 /
          (SELECT COUNT(DISTINCT (entry_date, timeslot_id))
           FROM schedule_entry), 2) AS load_pct
FROM room r
JOIN building b         ON r.building_id = b.building_id
LEFT JOIN schedule_entry s ON s.room_id  = r.room_id
LEFT JOIN timeslot t    ON s.timeslot_id = t.timeslot_id
GROUP BY b.name, r.room_type, r.name, t.day_of_week, t.pair_number, t.start_time
ORDER BY b.name, r.room_type, r.name, t.day_of_week, t.pair_number;


-- 6. Проверка пересечений в расписании группы
SELECT
    sg.name  AS group_name,
    t.day_of_week,
    t.pair_number,
    s.entry_date,
    COUNT(*) AS overlaps
FROM schedule_entry s
JOIN study_group sg ON s.group_id    = sg.group_id
JOIN timeslot t     ON s.timeslot_id = t.timeslot_id
GROUP BY sg.name, t.day_of_week, t.pair_number, s.entry_date
HAVING COUNT(*) > 1;


-- 7. Проверка: лаборатории только в аудиториях нужного типа
SELECT
    s.entry_id,
    sg.name   AS group_name,
    cs.name   AS subject,
    r.name    AS room,
    r.room_type
FROM schedule_entry s
JOIN lesson l           ON s.lesson_id   = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN study_group sg     ON s.group_id    = sg.group_id
JOIN room r             ON s.room_id     = r.room_id
WHERE l.lesson_type = 'lab'
  AND r.room_type NOT IN ('lab', 'computer');


-- 8. Проверка вместимости помещения для группы
SELECT
    s.entry_id,
    sg.name           AS group_name,
    sg.student_count,
    r.name            AS room,
    r.capacity
FROM schedule_entry s
JOIN study_group sg ON s.group_id = sg.group_id
JOIN room r         ON s.room_id  = r.room_id
WHERE sg.student_count > r.capacity;


-- 9. Проверка: преподаватель не более 5 пар в день
SELECT
    tch.last_name || ' ' || tch.first_name AS teacher,
    s.entry_date,
    COUNT(*) AS pairs_per_day
FROM schedule_entry s
JOIN teacher tch ON s.teacher_id = tch.teacher_id
GROUP BY tch.teacher_id, tch.last_name, tch.first_name, s.entry_date
HAVING COUNT(*) > 5;


-- 10. Проверка: группа не более 5 пар в день
SELECT
    sg.name  AS group_name,
    s.entry_date,
    COUNT(*) AS pairs_per_day
FROM schedule_entry s
JOIN study_group sg ON s.group_id = sg.group_id
GROUP BY sg.group_id, sg.name, s.entry_date
HAVING COUNT(*) > 5;


-- 11. Копирование расписания на новую дату
INSERT INTO schedule_entry (group_id, lesson_id, timeslot_id, teacher_id, room_id, entry_date)
SELECT
    group_id,
    lesson_id,
    timeslot_id,
    teacher_id,
    room_id,
    entry_date + :week_offset * INTERVAL '7 days'   -- сдвиг на N недель
FROM schedule_entry
WHERE entry_date BETWEEN :source_date_from AND :source_date_to;


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
SELECT
    tch.last_name || ' ' || tch.first_name AS teacher,
    l.lesson_type,
    COUNT(*)               AS sessions,
    SUM(l.duration_minutes) AS total_minutes,
    SUM(l.duration_minutes) / 45 AS academic_hours
FROM schedule_entry s
JOIN teacher tch        ON s.teacher_id = tch.teacher_id
JOIN lesson l           ON s.lesson_id  = l.lesson_id
WHERE s.entry_date BETWEEN :semester_start AND :semester_end
GROUP BY tch.teacher_id, tch.last_name, tch.first_name, l.lesson_type
ORDER BY tch.last_name, l.lesson_type;


-- 14. Дисциплины учебного плана для семестра
SELECT
    cs.subject_id,
    cs.name          AS subject,
    cs.lecture_hours,
    cs.practice_hours,
    cs.lab_hours,
    cs.assessment_type,
    c.weeks,
    ROUND(cs.lecture_hours::NUMERIC  / c.weeks, 2) AS lectures_per_week,
    ROUND(cs.practice_hours::NUMERIC / c.weeks, 2) AS practice_per_week,
    ROUND(cs.lab_hours::NUMERIC      / c.weeks, 2) AS labs_per_week
FROM curriculum_subject cs
JOIN curriculum c ON cs.curriculum_id = c.curriculum_id
WHERE c.curriculum_id = :curriculum_id
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
FROM schedule_entry s
JOIN study_group sg     ON s.group_id   = sg.group_id
JOIN lesson l           ON s.lesson_id  = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
WHERE l.lesson_type IN ('exam', 'pass_test')
ORDER BY sg.name, cs.name;
