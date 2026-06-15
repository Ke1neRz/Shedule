-- Часть 1: Структура таблиц (DDL)

CREATE TABLE university (
    university_id   SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    address         VARCHAR(300)
);

CREATE TABLE division (
    division_id     SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    parent_id       INTEGER REFERENCES division(division_id),
    university_id   INTEGER NOT NULL REFERENCES university(university_id)
);

CREATE TABLE teacher (
    teacher_id      SERIAL PRIMARY KEY,
    last_name       VARCHAR(100) NOT NULL,
    first_name      VARCHAR(100) NOT NULL,
    middle_name     VARCHAR(100),
    degree          VARCHAR(100),
    title           VARCHAR(100),
    position        VARCHAR(100),
    email           VARCHAR(100),
    division_id     INTEGER NOT NULL REFERENCES division(division_id)
);

CREATE TABLE curriculum (
    curriculum_id   SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    direction_code  VARCHAR(20),
    semester        SMALLINT NOT NULL,
    academic_year   SMALLINT NOT NULL,
    weeks           SMALLINT NOT NULL DEFAULT 18
);

CREATE TABLE curriculum_subject (
    subject_id      SERIAL PRIMARY KEY,
    curriculum_id   INTEGER NOT NULL REFERENCES curriculum(curriculum_id),
    name            VARCHAR(200) NOT NULL,
    lecture_hours   SMALLINT NOT NULL DEFAULT 0,
    practice_hours  SMALLINT NOT NULL DEFAULT 0,
    lab_hours       SMALLINT NOT NULL DEFAULT 0,
    assessment_type VARCHAR(10) NOT NULL CHECK (assessment_type IN ('exam', 'pass'))
);

CREATE TABLE academic_group (
    academic_group_id SERIAL PRIMARY KEY,
    group_number      VARCHAR(20) NOT NULL,
    curriculum_id     INTEGER NOT NULL REFERENCES curriculum(curriculum_id)
);

CREATE TABLE study_group (
    group_id        SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    student_count   SMALLINT NOT NULL CHECK (student_count > 0),
    curriculum_id   INTEGER NOT NULL REFERENCES curriculum(curriculum_id)
);

CREATE TABLE study_group_academic_group (
    study_group_id      INTEGER NOT NULL REFERENCES study_group(group_id) ON DELETE CASCADE,
    academic_group_id   INTEGER NOT NULL REFERENCES academic_group(academic_group_id) ON DELETE CASCADE,
    PRIMARY KEY (study_group_id, academic_group_id)
);

CREATE TABLE lesson (
    lesson_id       SERIAL PRIMARY KEY,
    subject_id      INTEGER NOT NULL REFERENCES curriculum_subject(subject_id),
    lesson_type     VARCHAR(20) NOT NULL CHECK (lesson_type IN
                        ('lecture','practice','lab','exam','pass_test','consult','internship')),
    duration_minutes SMALLINT NOT NULL
);

CREATE TABLE teacher_lesson (
    teacher_id  INTEGER NOT NULL REFERENCES teacher(teacher_id) ON DELETE CASCADE,
    lesson_id   INTEGER NOT NULL REFERENCES lesson(lesson_id) ON DELETE CASCADE,
    PRIMARY KEY (teacher_id, lesson_id)
);

CREATE TABLE building (
    building_id     SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    address         VARCHAR(300)
);

CREATE TABLE building_distance (
    from_building_id INTEGER NOT NULL REFERENCES building(building_id),
    to_building_id   INTEGER NOT NULL REFERENCES building(building_id),
    distance_minutes SMALLINT NOT NULL,
    PRIMARY KEY (from_building_id, to_building_id),
    CHECK (from_building_id <> to_building_id)
);

CREATE TABLE room (
    room_id         SERIAL PRIMARY KEY,
    name            VARCHAR(20) NOT NULL UNIQUE,
    building_id     INTEGER NOT NULL REFERENCES building(building_id),
    room_type       VARCHAR(20) NOT NULL CHECK (room_type IN
                        ('lecture','practice','lab','computer')),
    capacity        SMALLINT NOT NULL CHECK (capacity > 0)
);

CREATE TABLE timeslot (
    timeslot_id     SERIAL PRIMARY KEY,
    day_of_week     SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 6),
    pair_number     SMALLINT NOT NULL CHECK (pair_number BETWEEN 1 AND 8),
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    UNIQUE (day_of_week, pair_number)
);

CREATE TABLE work_calendar (
    calendar_id     SERIAL PRIMARY KEY,
    calendar_date   DATE NOT NULL UNIQUE,
    is_working      BOOLEAN NOT NULL DEFAULT TRUE,
    is_holiday      BOOLEAN NOT NULL DEFAULT FALSE,
    note            VARCHAR(200)
);

CREATE TABLE schedule_entry (
    entry_id        SERIAL PRIMARY KEY,
    group_id        INTEGER NOT NULL REFERENCES study_group(group_id),
    lesson_id       INTEGER NOT NULL REFERENCES lesson(lesson_id),
    timeslot_id     INTEGER NOT NULL REFERENCES timeslot(timeslot_id),
    teacher_id      INTEGER NOT NULL REFERENCES teacher(teacher_id),
    room_id         INTEGER REFERENCES room(room_id),
    entry_date      DATE NOT NULL,
    week_parity     VARCHAR(10) NOT NULL DEFAULT 'all' CHECK (week_parity IN ('all','even','odd')),
    is_online       BOOLEAN NOT NULL DEFAULT FALSE,
    online_link     VARCHAR(500)
);

CREATE TABLE teacher_preference (
    preference_id   SERIAL PRIMARY KEY,
    teacher_id      INTEGER NOT NULL REFERENCES teacher(teacher_id) ON DELETE CASCADE,
    day_of_week     SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 6),
    pair_number     SMALLINT NOT NULL CHECK (pair_number BETWEEN 1 AND 8),
    is_preferred    BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (teacher_id, day_of_week, pair_number)
);

-- Индексы / ограничения

CREATE UNIQUE INDEX uix_room_timeslot
    ON schedule_entry (room_id, timeslot_id, entry_date) WHERE room_id IS NOT NULL;

CREATE UNIQUE INDEX uix_teacher_timeslot
    ON schedule_entry (teacher_id, timeslot_id, entry_date);

CREATE UNIQUE INDEX uix_group_timeslot
    ON schedule_entry (group_id, timeslot_id, entry_date);

-- Часть 2: Seed (демо-данные)

-- Университет
INSERT INTO university (name, address) VALUES
('Университет ИТ', 'г. Москва, ул. Примерная, 1');

-- Подразделения (иерархия)
INSERT INTO division (name, parent_id, university_id) VALUES
('Школа информационных технологий', NULL, 1),
('Кафедра ИВТ', 1, 1),
('Кафедра Программной инженерии', 1, 1);

-- Преподаватели
INSERT INTO teacher (last_name, first_name, middle_name, degree, title, position, email, division_id) VALUES
('Иванов', 'Иван', 'Иванович', 'к.т.н.', 'доцент', 'доцент', 'ivanov@university.ru', 2),
('Петров', 'Петр', 'Петрович', 'к.ф.-м.н.', 'доцент', 'доцент', 'petrov@university.ru', 2),
('Сидоров', 'Сидор', 'Сидорович', 'д.т.н.', 'профессор', 'зав. кафедрой', 'sidorov@university.ru', 2),
('Кузнецова', 'Анна', 'Андреевна', 'к.п.н.', 'ст. преподаватель', 'ст. преподаватель', 'kuznetsova@university.ru', 3);

-- Учебный план (1 семестр, 2024)
INSERT INTO curriculum (name, direction_code, semester, academic_year, weeks) VALUES
('09.03.01 Информатика и вычислительная техника, 1 курс', '09.03.01', 1, 2024, 18);

-- Дисциплины
INSERT INTO curriculum_subject (curriculum_id, name, lecture_hours, practice_hours, lab_hours, assessment_type) VALUES
(1, 'Математика', 36, 36, 0, 'pass'),
(1, 'Программирование', 36, 0, 36, 'exam'),
(1, 'Информатика', 18, 18, 0, 'pass'),
(1, 'Физика', 18, 18, 0, 'exam'),
(1, 'Практика', 0, 0, 0, 'pass');

-- Академические группы
INSERT INTO academic_group (group_number, curriculum_id) VALUES
('ИВТ-101', 1),
('ИВТ-102', 1);

-- Учебные группы
INSERT INTO study_group (name, student_count, curriculum_id) VALUES
('ИВТ-101', 20, 1),
('ИВТ-101-подгруппа1', 10, 1),
('ИВТ-101-подгруппа2', 10, 1),
('ИВТ-102', 20, 1),
('ИВТ-102-подгруппа1', 10, 1),
('Поток ИВТ-101+102', 40, 1),
('ИВТ-101 (физра)', 20, 1);

-- Связи академических и учебных групп
INSERT INTO study_group_academic_group (study_group_id, academic_group_id) VALUES
(1, 1),   -- ИВТ-101
(2, 1),   -- подгруппа1
(3, 1),   -- подгруппа2
(4, 2),   -- ИВТ-102
(5, 2),   -- подгруппа1
(6, 1),   -- поток ИВТ-101
(6, 2),   -- поток ИВТ-102
(7, 1);   -- физра ИВТ-101

-- Учебные занятия (пары в неделю)
INSERT INTO lesson (subject_id, lesson_type, duration_minutes) VALUES
-- Математика
(1, 'lecture', 90), (1, 'practice', 90), (1, 'pass_test', 200),
-- Программирование
(2, 'lecture', 90), (2, 'lab', 90), (2, 'exam', 400), (2, 'consult', 90),
-- Информатика
(3, 'lecture', 90), (3, 'practice', 90), (3, 'pass_test', 200),
-- Физика
(4, 'lecture', 90), (4, 'practice', 90), (4, 'exam', 400), (4, 'consult', 90),
-- Практика
(5, 'internship', 180);

-- Связи преподавателей с занятиями
INSERT INTO teacher_lesson (teacher_id, lesson_id) VALUES
(1, 1), (1, 2), (1, 3),   -- Иванов: Математика
(2, 4), (2, 5), (2, 6), (2, 7), (2, 15), -- Петров: Программирование + Практика
(3, 8), (3, 9), (3, 10),   -- Сидоров: Информатика
(4, 11), (4, 12), (4, 13), (4, 14); -- Кузнецова: Физика

-- Корпуса
INSERT INTO building (name, address) VALUES
('Корпус 1', 'ул. Примерная, 1'),
('Корпус 2', 'ул. Примерная, 3');

-- Расстояния между корпусами
INSERT INTO building_distance (from_building_id, to_building_id, distance_minutes) VALUES
(1, 2, 10), (2, 1, 10);

-- Аудитории
INSERT INTO room (name, building_id, room_type, capacity) VALUES
('101', 1, 'lecture', 50),
('201', 1, 'practice', 30),
('301', 2, 'lab', 20),
('302', 2, 'computer', 25),
('303', 2, 'lab', 15),
('102', 1, 'lecture', 60);

-- Справочник звонков (пары)
INSERT INTO timeslot (day_of_week, pair_number, start_time, end_time)
SELECT d, p, s::TIME, e::TIME
FROM (VALUES
  (1,'08:30','10:00'), (2,'10:10','11:40'), (3,'11:50','13:20'),
  (4,'13:30','15:00'), (5,'15:10','16:40'), (6,'16:50','18:20'),
  (7,'18:30','20:00'), (8,'19:10','20:40')
) slots(p,s,e)
CROSS JOIN generate_series(1,6) d;

-- Рабочий календарь (1 семестр 2024: сентябрь - январь)
-- Даты с 01.09.2024 по 31.01.2025: сб = рабочая, вс = выходной, праздники отмечены
INSERT INTO work_calendar (calendar_date, is_working, is_holiday, note)
SELECT d::DATE,
       CASE WHEN EXTRACT(DOW FROM d::DATE) = 0 THEN FALSE ELSE TRUE END,
       CASE WHEN d::DATE IN ('2024-11-04','2024-12-31','2025-01-01','2025-01-02','2025-01-03',
                             '2025-01-04','2025-01-05','2025-01-06','2025-01-07','2025-01-08') THEN TRUE ELSE FALSE END,
       CASE WHEN d::DATE = '2024-11-04' THEN 'День народного единства'
            WHEN d::DATE IN ('2024-12-31','2025-01-01','2025-01-02','2025-01-03',
                             '2025-01-04','2025-01-05','2025-01-06','2025-01-07','2025-01-08') THEN 'Новогодние каникулы'
            ELSE NULL END
FROM generate_series('2024-09-01'::DATE, '2025-01-31'::DATE, '1 day'::INTERVAL) d;

-- Предпочтения преподавателей (примеры)
INSERT INTO teacher_preference (teacher_id, day_of_week, pair_number, is_preferred) VALUES
(1, 1, 1, TRUE), (1, 1, 2, TRUE), (1, 3, 1, TRUE), (1, 5, 1, FALSE);
