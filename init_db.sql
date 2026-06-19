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
    direction_code  VARCHAR(20) NOT NULL,
    admission_year  SMALLINT NOT NULL,
    duration_years  SMALLINT NOT NULL DEFAULT 4 CHECK (duration_years > 0)
);

CREATE TABLE curriculum_semester (
    semester_id     SERIAL PRIMARY KEY,
    curriculum_id   INTEGER NOT NULL REFERENCES curriculum(curriculum_id),
    semester_number SMALLINT NOT NULL CHECK (semester_number BETWEEN 1 AND 12),
    academic_year   SMALLINT NOT NULL,
    weeks           SMALLINT NOT NULL DEFAULT 18 CHECK (weeks >= 18),
    start_date      DATE GENERATED ALWAYS AS (
        CASE WHEN semester_number % 2 = 1
             THEN MAKE_DATE(academic_year, 9, 1)
             ELSE MAKE_DATE(academic_year, 2, 1)
        END
    ) STORED,
    end_date        DATE GENERATED ALWAYS AS (
        CASE WHEN semester_number % 2 = 1
             THEN MAKE_DATE(academic_year + 1, 1, 31)
             ELSE MAKE_DATE(academic_year, 6, 30)
        END
    ) STORED,
    UNIQUE (curriculum_id, semester_number)
);

CREATE TABLE curriculum_subject (
    subject_id      SERIAL PRIMARY KEY,
    semester_id     INTEGER NOT NULL REFERENCES curriculum_semester(semester_id),
    name            VARCHAR(200) NOT NULL,
    lecture_hours   SMALLINT NOT NULL DEFAULT 0,
    practice_hours  SMALLINT NOT NULL DEFAULT 0,
    lab_hours       SMALLINT NOT NULL DEFAULT 0,
    assessment_type VARCHAR(10) NOT NULL CHECK (assessment_type IN ('exam', 'pass')),
    UNIQUE (semester_id, name)
);

CREATE TABLE academic_group (
    academic_group_id SERIAL PRIMARY KEY,
    group_number      VARCHAR(20) NOT NULL,
    curriculum_id     INTEGER NOT NULL REFERENCES curriculum(curriculum_id),
    UNIQUE (curriculum_id, group_number)
);

CREATE TABLE study_group (
    group_id        SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    student_count   SMALLINT NOT NULL CHECK (student_count > 0),
    semester_id     INTEGER NOT NULL REFERENCES curriculum_semester(semester_id)
);

CREATE TABLE study_group_academic_group (
    study_group_id      INTEGER NOT NULL REFERENCES study_group(group_id) ON DELETE CASCADE,
    academic_group_id   INTEGER NOT NULL REFERENCES academic_group(academic_group_id) ON DELETE CASCADE,
    PRIMARY KEY (study_group_id, academic_group_id)
);

CREATE TABLE lesson (
    lesson_id       SERIAL PRIMARY KEY,
    subject_id      INTEGER NOT NULL REFERENCES curriculum_subject(subject_id) ON DELETE CASCADE,
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

-- Шаблон расписания на семестр: задаёт "каждую <чёт/нечёт/любую> неделю в <день> <пара> — <предмет> у <препода> в <ауд>"
CREATE TABLE schedule_template (
    template_id     SERIAL PRIMARY KEY,
    semester_id     INTEGER NOT NULL REFERENCES curriculum_semester(semester_id) ON DELETE CASCADE,
    group_id        INTEGER NOT NULL REFERENCES study_group(group_id) ON DELETE CASCADE,
    day_of_week     SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 6),
    pair_number     SMALLINT NOT NULL CHECK (pair_number BETWEEN 1 AND 8),
    week_parity     VARCHAR(10) NOT NULL DEFAULT 'all' CHECK (week_parity IN ('all','even','odd')),
    lesson_id       INTEGER NOT NULL REFERENCES lesson(lesson_id),
    teacher_id      INTEGER NOT NULL REFERENCES teacher(teacher_id),
    room_id         INTEGER REFERENCES room(room_id),
    is_online       BOOLEAN NOT NULL DEFAULT FALSE,
    online_link     VARCHAR(500),
    UNIQUE (semester_id, group_id, day_of_week, pair_number, week_parity)
);

-- Разовые исключения на конкретные даты: замена, доп. пара, отмена
CREATE TABLE schedule_exception (
    exception_id    SERIAL PRIMARY KEY,
    exception_type  VARCHAR(10) NOT NULL CHECK (exception_type IN ('replace','add','cancel')),
    -- для replace/cancel указывается template_id
    template_id     INTEGER REFERENCES schedule_template(template_id) ON DELETE CASCADE,
    -- для add без шаблона — указывается ячейка вручную
    group_id        INTEGER REFERENCES study_group(group_id),
    day_of_week     SMALLINT CHECK (day_of_week IS NULL OR day_of_week BETWEEN 1 AND 6),
    pair_number     SMALLINT CHECK (pair_number IS NULL OR pair_number BETWEEN 1 AND 8),
    week_parity     VARCHAR(10) CHECK (week_parity IS NULL OR week_parity IN ('all','even','odd')),
    entry_date      DATE NOT NULL,
    -- переопределение (для replace/add): null-поля = использовать значения из шаблона
    lesson_id       INTEGER REFERENCES lesson(lesson_id),
    teacher_id      INTEGER REFERENCES teacher(teacher_id),
    room_id         INTEGER REFERENCES room(room_id),
    is_online       BOOLEAN,
    online_link     VARCHAR(500),
    note            VARCHAR(200),
    CHECK (
        (exception_type IN ('replace','cancel') AND template_id IS NOT NULL)
     OR (exception_type = 'add' AND template_id IS NULL
         AND group_id IS NOT NULL AND day_of_week IS NOT NULL
         AND pair_number IS NOT NULL AND lesson_id IS NOT NULL
         AND teacher_id IS NOT NULL)
    )
);

CREATE INDEX ix_exception_template_date
    ON schedule_exception (template_id, entry_date);
CREATE INDEX ix_exception_group_date
    ON schedule_exception (group_id, entry_date);

CREATE TABLE teacher_preference (
    preference_id   SERIAL PRIMARY KEY,
    teacher_id      INTEGER NOT NULL REFERENCES teacher(teacher_id) ON DELETE CASCADE,
    day_of_week     SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 6),
    pair_number     SMALLINT NOT NULL CHECK (pair_number BETWEEN 1 AND 8),
    is_preferred    BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (teacher_id, day_of_week, pair_number)
);

-- Индексы / ограничения

-- (уникальность ячеек шаблона обеспечивается UNIQUE в DDL schedule_template)
-- Конфликты по дате (помещение/преподаватель/группа) проверяются на уровне приложения
-- с учётом шаблона + исключений, т.к. шаблон задаёт правило для всех дат семестра.

-- Функция-триггер: лабораторные только в lab/computer (на schedule_template)
CREATE OR REPLACE FUNCTION check_template_lab_room()
RETURNS TRIGGER AS $$
DECLARE
    v_type VARCHAR(20);
    v_room VARCHAR(20);
BEGIN
    SELECT lesson_type INTO v_type FROM lesson WHERE lesson_id = NEW.lesson_id;

    IF v_type = 'lab' AND NEW.room_id IS NOT NULL THEN
        SELECT room_type INTO v_room FROM room WHERE room_id = NEW.room_id;
        IF v_room NOT IN ('lab', 'computer') THEN
            RAISE EXCEPTION 'Лабораторное занятие — только в lab/computer, а не в "%".', v_room;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_template_lab_room
BEFORE INSERT OR UPDATE ON schedule_template
FOR EACH ROW EXECUTE FUNCTION check_template_lab_room();

-- Функция-триггер: проверка work_calendar для исключений типа 'add'
-- (для replace/cancel entry_date может совпадать с праздником — это допустимо)
CREATE OR REPLACE FUNCTION check_exception_work_calendar()
RETURNS TRIGGER AS $$
DECLARE
    v_working BOOLEAN;
    v_holiday BOOLEAN;
    v_note    VARCHAR(200);
BEGIN
    IF NEW.exception_type <> 'add' THEN
        RETURN NEW;
    END IF;

    SELECT is_working, is_holiday, note
    INTO v_working, v_holiday, v_note
    FROM work_calendar
    WHERE calendar_date = NEW.entry_date;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Дата % отсутствует в производственном календаре (work_calendar). Сначала добавьте день в календарь.', NEW.entry_date;
    END IF;

    IF NOT v_working THEN
        RAISE EXCEPTION 'Дата % — нерабочий день по производственному календарю. Добавлять пару нельзя.', NEW.entry_date;
    END IF;

    IF v_holiday THEN
        RAISE EXCEPTION 'Дата % — праздничный день (%). Добавлять пару нельзя.', NEW.entry_date, COALESCE(v_note, 'праздник');
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_exception_work_calendar
BEFORE INSERT OR UPDATE ON schedule_exception
FOR EACH ROW EXECUTE FUNCTION check_exception_work_calendar();

-- Функция-триггер: лабораторные только в lab/computer (на schedule_exception)
CREATE OR REPLACE FUNCTION check_exception_lab_room()
RETURNS TRIGGER AS $$
DECLARE
    v_type VARCHAR(20);
    v_room VARCHAR(20);
BEGIN
    IF NEW.lesson_id IS NULL OR NEW.room_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT lesson_type INTO v_type FROM lesson WHERE lesson_id = NEW.lesson_id;

    IF v_type = 'lab' THEN
        SELECT room_type INTO v_room FROM room WHERE room_id = NEW.room_id;
        IF v_room NOT IN ('lab', 'computer') THEN
            RAISE EXCEPTION 'Лабораторное занятие (исключение) — только в lab/computer, а не в "%".', v_room;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_exception_lab_room
BEFORE INSERT OR UPDATE ON schedule_exception
FOR EACH ROW EXECUTE FUNCTION check_exception_lab_room();

-- Часть 2: Seed (демо-данные)

-- Перед заливкой чистим все таблицы и сбрасываем счётчики — делает скрипт идемпотентным
-- (повторный запуск даёт ровно те же данные, без дублей).
TRUNCATE TABLE
    schedule_exception, schedule_template, work_calendar, teacher_preference,
    teacher_lesson, lesson, curriculum_subject, academic_group,
    study_group_academic_group, study_group, room, building_distance, building,
    timeslot, teacher, division, university, curriculum_semester, curriculum
RESTART IDENTITY CASCADE;

-- Университет
INSERT INTO university (name, address) VALUES
('Университет ИТ', 'г. Москва, ул. Примерная, 1');

-- Подразделения (иерархия)
INSERT INTO division (name, parent_id, university_id) VALUES
('Школа информационных технологий', NULL, 1),
('Кафедра ИВТ', 1, 1),
('Кафедра Программной инженерии', 1, 1);

-- Преподаватели (6 — для распределения нагрузки по 8 семестрам)
INSERT INTO teacher (last_name, first_name, middle_name, degree, title, position, email, division_id) VALUES
('Иванов', 'Иван', 'Иванович', 'к.т.н.', 'доцент', 'доцент', 'ivanov@university.ru', 2),
('Петров', 'Петр', 'Петрович', 'к.ф.-м.н.', 'доцент', 'доцент', 'petrov@university.ru', 2),
('Сидоров', 'Сидор', 'Сидорович', 'д.т.н.', 'профессор', 'зав. кафедрой', 'sidorov@university.ru', 2),
('Кузнецова', 'Анна', 'Андреевна', 'к.п.н.', 'ст. преподаватель', 'ст. преподаватель', 'kuznetsova@university.ru', 3),
('Кравцов', 'Андрей', 'Сергеевич', 'к.т.н.', 'доцент', 'доцент', 'kravtsov@university.ru', 3),
('Морозова', 'Елена', 'Викторовна', 'к.ф.-м.н.', 'доцент', 'доцент', 'morozova@university.ru', 2);

-- Учебный план (09.03.01, набор 2024, 4 года = 8 семестров)
INSERT INTO curriculum (name, direction_code, admission_year, duration_years) VALUES
('09.03.01 Информатика и вычислительная техника', '09.03.01', 2024, 4);

-- 8 семестров учебного плана (осенние/весенние, 18 недель каждый)
INSERT INTO curriculum_semester (curriculum_id, semester_number, academic_year, weeks) VALUES
(1, 1, 2024, 18),  -- осенний 2024
(1, 2, 2025, 18),  -- весенний 2025
(1, 3, 2025, 18),  -- осенний 2025
(1, 4, 2026, 18),  -- весенний 2026
(1, 5, 2026, 18),  -- осенний 2026
(1, 6, 2027, 18),  -- весенний 2027
(1, 7, 2027, 18),  -- осенний 2027
(1, 8, 2028, 18);  -- весенний 2028

-- Дисциплины по семестрам (набор разный в каждом семестре)
INSERT INTO curriculum_subject (semester_id, name, lecture_hours, practice_hours, lab_hours, assessment_type) VALUES
-- 1 семестр (1 курс, осень): базовые дисциплины
(1, 'Математический анализ',   54, 54,  0, 'exam'),
(1, 'Программирование',        36,  0, 54, 'exam'),
(1, 'Информатика',             18, 36,  0, 'pass'),
(1, 'Физика',                  36, 36,  0, 'exam'),
(1, 'Английский язык',          0, 54,  0, 'pass'),
(1, 'История',                 36, 18,  0, 'pass'),
-- 2 семестр (1 курс, весна): продолжение базы
(2, 'Математический анализ',   54, 54,  0, 'exam'),
(2, 'Дискретная математика',   36, 36,  0, 'exam'),
(2, 'Алгоритмы и структуры данных', 36, 0, 36, 'exam'),
(2, 'Физика',                  36, 36, 18, 'pass'),
(2, 'Английский язык',          0, 54,  0, 'pass'),
(2, 'Физкультура',              0, 72,  0, 'pass'),
-- 3 семестр (2 курс, осень): специализация
(3, 'Линейная алгебра',        36, 36,  0, 'exam'),
(3, 'Базы данных',             36,  0, 54, 'exam'),
(3, 'Объектно-ориентированное программирование', 36, 0, 36, 'exam'),
(3, 'Веб-разработка',          18,  0, 36, 'pass'),
(3, 'Английский язык',          0, 36,  0, 'pass'),
-- 4 семестр (2 курс, весна)
(4, 'Теория вероятностей',     36, 36,  0, 'exam'),
(4, 'Базы данных',             36,  0, 36, 'exam'),
(4, 'Компьютерные сети',       36,  0, 36, 'exam'),
(4, 'Операционные системы',    36,  0, 36, 'pass'),
(4, 'Физкультура',              0, 36,  0, 'pass'),
-- 5 семестр (3 курс, осень)
(5, 'Архитектура ПО',          36, 18,  0, 'exam'),
(5, 'Машинное обучение',       36,  0, 36, 'exam'),
(5, 'Мобильная разработка',    18,  0, 36, 'pass'),
(5, 'Математическая статистика', 36, 36, 0, 'pass'),
(5, 'Английский язык',          0, 36,  0, 'pass'),
-- 6 семестр (3 курс, весна)
(6, 'Архитектура ПО',          36, 18,  0, 'exam'),
(6, 'Машинное обучение',       18,  0, 36, 'pass'),
(6, 'DevOps и облачные технологии', 36, 0, 36, 'exam'),
(6, 'Математическая статистика', 36, 36, 0, 'exam'),
(6, 'Физкультура',              0, 36,  0, 'pass'),
-- 7 семестр (4 курс, осень)
(7, 'Управление проектами',    36, 36,  0, 'exam'),
(7, 'Информационная безопасность', 36, 0, 36, 'exam'),
(7, 'Распределённые системы',  36,  0, 36, 'pass'),
(7, 'Английский язык',          0, 36,  0, 'pass'),
-- 8 семестр (4 курс, весна): диплом
(8, 'Управление проектами',    18, 18,  0, 'pass'),
(8, 'Преддипломная практика',   0,  0,  0, 'pass'),
(8, 'Подготовка ВКР',           0,  0,  0, 'pass');

-- Занятия по дисциплинам (лекции/практики/лабы/экзамены/зачёты/консультации).
-- Один INSERT — для каждой дисциплины выбираем нужные типы занятий и длительность.
INSERT INTO lesson (subject_id, lesson_type, duration_minutes)
SELECT cs.subject_id, v.lesson_type, v.duration_minutes
FROM (VALUES
    -- 1 семестр
    (1, 'Математический анализ',                 'lecture',    90),
    (1, 'Математический анализ',                 'practice',   90),
    (1, 'Математический анализ',                 'exam',      400),
    (1, 'Математический анализ',                 'consult',    90),
    (1, 'Программирование',                      'lecture',    90),
    (1, 'Программирование',                      'lab',        90),
    (1, 'Программирование',                      'exam',      400),
    (1, 'Программирование',                      'consult',    90),
    (1, 'Информатика',                           'lecture',    90),
    (1, 'Информатика',                           'practice',   90),
    (1, 'Информатика',                           'pass_test', 200),
    (1, 'Физика',                                'lecture',    90),
    (1, 'Физика',                                'practice',   90),
    (1, 'Физика',                                'exam',      400),
    (1, 'Физика',                                'consult',    90),
    (1, 'Английский язык',                       'practice',   90),
    (1, 'Английский язык',                       'pass_test', 200),
    (1, 'История',                               'lecture',    90),
    (1, 'История',                               'practice',   90),
    (1, 'История',                               'pass_test', 200),
    -- 2 семестр
    (2, 'Математический анализ',                 'lecture',    90),
    (2, 'Математический анализ',                 'practice',   90),
    (2, 'Математический анализ',                 'exam',      400),
    (2, 'Дискретная математика',                 'lecture',    90),
    (2, 'Дискретная математика',                 'practice',   90),
    (2, 'Дискретная математика',                 'exam',      400),
    (2, 'Алгоритмы и структуры данных',          'lecture',    90),
    (2, 'Алгоритмы и структуры данных',          'lab',        90),
    (2, 'Алгоритмы и структуры данных',          'exam',      400),
    (2, 'Алгоритмы и структуры данных',          'consult',    90),
    (2, 'Физика',                                'lecture',    90),
    (2, 'Физика',                                'practice',   90),
    (2, 'Физика',                                'lab',        90),
    (2, 'Физика',                                'pass_test', 200),
    (2, 'Английский язык',                       'practice',   90),
    (2, 'Английский язык',                       'pass_test', 200),
    (2, 'Физкультура',                           'practice',   90),
    (2, 'Физкультура',                           'pass_test', 200),
    -- 3 семестр
    (3, 'Линейная алгебра',                      'lecture',    90),
    (3, 'Линейная алгебра',                      'practice',   90),
    (3, 'Линейная алгебра',                      'exam',      400),
    (3, 'Базы данных',                           'lecture',    90),
    (3, 'Базы данных',                           'lab',        90),
    (3, 'Базы данных',                           'exam',      400),
    (3, 'Объектно-ориентированное программирование', 'lecture', 90),
    (3, 'Объектно-ориентированное программирование', 'lab',     90),
    (3, 'Объектно-ориентированное программирование', 'exam',   400),
    (3, 'Веб-разработка',                        'lecture',    90),
    (3, 'Веб-разработка',                        'lab',        90),
    (3, 'Веб-разработка',                        'pass_test', 200),
    (3, 'Английский язык',                       'practice',   90),
    (3, 'Английский язык',                       'pass_test', 200),
    -- 4 семестр
    (4, 'Теория вероятностей',                   'lecture',    90),
    (4, 'Теория вероятностей',                   'practice',   90),
    (4, 'Теория вероятностей',                   'exam',      400),
    (4, 'Базы данных',                           'lecture',    90),
    (4, 'Базы данных',                           'lab',        90),
    (4, 'Базы данных',                           'exam',      400),
    (4, 'Компьютерные сети',                     'lecture',    90),
    (4, 'Компьютерные сети',                     'lab',        90),
    (4, 'Компьютерные сети',                     'exam',      400),
    (4, 'Операционные системы',                  'lecture',    90),
    (4, 'Операционные системы',                  'lab',        90),
    (4, 'Операционные системы',                  'pass_test', 200),
    (4, 'Физкультура',                           'practice',   90),
    (4, 'Физкультура',                           'pass_test', 200),
    -- 5 семестр
    (5, 'Архитектура ПО',                        'lecture',    90),
    (5, 'Архитектура ПО',                        'practice',   90),
    (5, 'Архитектура ПО',                        'exam',      400),
    (5, 'Архитектура ПО',                        'consult',    90),
    (5, 'Машинное обучение',                     'lecture',    90),
    (5, 'Машинное обучение',                     'lab',        90),
    (5, 'Машинное обучение',                     'exam',      400),
    (5, 'Мобильная разработка',                  'lecture',    90),
    (5, 'Мобильная разработка',                  'lab',        90),
    (5, 'Мобильная разработка',                  'pass_test', 200),
    (5, 'Математическая статистика',             'lecture',    90),
    (5, 'Математическая статистика',             'practice',   90),
    (5, 'Математическая статистика',             'pass_test', 200),
    (5, 'Английский язык',                       'practice',   90),
    (5, 'Английский язык',                       'pass_test', 200),
    -- 6 семестр
    (6, 'Архитектура ПО',                        'lecture',    90),
    (6, 'Архитектура ПО',                        'practice',   90),
    (6, 'Архитектура ПО',                        'exam',      400),
    (6, 'Машинное обучение',                     'lecture',    90),
    (6, 'Машинное обучение',                     'lab',        90),
    (6, 'Машинное обучение',                     'pass_test', 200),
    (6, 'DevOps и облачные технологии',          'lecture',    90),
    (6, 'DevOps и облачные технологии',          'lab',        90),
    (6, 'DevOps и облачные технологии',          'exam',      400),
    (6, 'Математическая статистика',             'lecture',    90),
    (6, 'Математическая статистика',             'practice',   90),
    (6, 'Математическая статистика',             'exam',      400),
    (6, 'Физкультура',                           'practice',   90),
    (6, 'Физкультура',                           'pass_test', 200),
    -- 7 семестр
    (7, 'Управление проектами',                  'lecture',    90),
    (7, 'Управление проектами',                  'practice',   90),
    (7, 'Управление проектами',                  'exam',      400),
    (7, 'Информационная безопасность',           'lecture',    90),
    (7, 'Информационная безопасность',           'lab',        90),
    (7, 'Информационная безопасность',           'exam',      400),
    (7, 'Распределённые системы',                'lecture',    90),
    (7, 'Распределённые системы',                'lab',        90),
    (7, 'Распределённые системы',                'pass_test', 200),
    (7, 'Английский язык',                       'practice',   90),
    (7, 'Английский язык',                       'pass_test', 200),
    -- 8 семестр
    (8, 'Управление проектами',                  'lecture',    90),
    (8, 'Управление проектами',                  'practice',   90),
    (8, 'Управление проектами',                  'pass_test', 200),
    (8, 'Преддипломная практика',                'internship',180),
    (8, 'Преддипломная практика',                'pass_test', 200),
    (8, 'Подготовка ВКР',                        'consult',    90)
) AS v(semester_id, subject_name, lesson_type, duration_minutes)
JOIN curriculum_subject cs
  ON cs.semester_id = v.semester_id AND cs.name = v.subject_name;

-- Назначение преподавателей на дисциплины (по семестрам)
INSERT INTO teacher_lesson (teacher_id, lesson_id)
SELECT DISTINCT tch.teacher_id, l.lesson_id
FROM (VALUES
    -- Иванов: математика, линейная алгебра, теория вероятностей
    ('Иванов', 1, 'Математический анализ'),
    ('Иванов', 2, 'Математический анализ'),
    ('Иванов', 3, 'Линейная алгебра'),
    ('Иванов', 4, 'Теория вероятностей'),
    -- Петров: программирование, алгоритмы, ООП
    ('Петров', 1, 'Программирование'),
    ('Петров', 2, 'Алгоритмы и структуры данных'),
    ('Петров', 3, 'Объектно-ориентированное программирование'),
    -- Сидоров: информатика, дискретная математика, архитектура ПО
    ('Сидоров', 1, 'Информатика'),
    ('Сидоров', 2, 'Дискретная математика'),
    ('Сидоров', 5, 'Архитектура ПО'),
    ('Сидоров', 6, 'Архитектура ПО'),
    -- Кузнецова: физика, английский, история, физкультура
    ('Кузнецова', 1, 'Физика'),
    ('Кузнецова', 2, 'Физика'),
    ('Кузнецова', 1, 'Английский язык'),
    ('Кузнецова', 2, 'Английский язык'),
    ('Кузнецова', 3, 'Английский язык'),
    ('Кузнецова', 5, 'Английский язык'),
    ('Кузнецова', 7, 'Английский язык'),
    ('Кузнецова', 1, 'История'),
    ('Кузнецова', 2, 'Физкультура'),
    ('Кузнецова', 4, 'Физкультура'),
    ('Кузнецова', 6, 'Физкультура'),
    -- Кравцов: базы данных, веб, ОС, сети
    ('Кравцов', 3, 'Базы данных'),
    ('Кравцов', 4, 'Базы данных'),
    ('Кравцов', 3, 'Веб-разработка'),
    ('Кравцов', 4, 'Операционные системы'),
    ('Кравцов', 4, 'Компьютерные сети'),
    ('Кравцов', 6, 'DevOps и облачные технологии'),
    -- Морозова: ML, мобильная, стата, безопасность, распределённые, управление
    ('Морозова', 5, 'Машинное обучение'),
    ('Морозова', 6, 'Машинное обучение'),
    ('Морозова', 5, 'Мобильная разработка'),
    ('Морозова', 5, 'Математическая статистика'),
    ('Морозова', 6, 'Математическая статистика'),
    ('Морозова', 7, 'Информационная безопасность'),
    ('Морозова', 7, 'Распределённые системы'),
    ('Морозова', 7, 'Управление проектами'),
    ('Морозова', 8, 'Управление проектами'),
    ('Морозова', 8, 'Подготовка ВКР'),
    ('Морозова', 8, 'Преддипломная практика')
) AS a(teacher_last, semester_id, subject_name)
JOIN teacher tch ON tch.last_name = a.teacher_last
JOIN curriculum_subject cs ON cs.semester_id = a.semester_id AND cs.name = a.subject_name
JOIN lesson l ON l.subject_id = cs.subject_id;

-- Академические группы (по одной на каждый курс: 1-4)
INSERT INTO academic_group (group_number, curriculum_id) VALUES
('ИВТ-1', 1),
('ИВТ-2', 1),
('ИВТ-3', 1),
('ИВТ-4', 1);

-- Учебные группы: по одной на каждый семестр (1..8)
INSERT INTO study_group (name, student_count, semester_id) VALUES
('ИВТ-1 (1 семестр)', 25, 1),
('ИВТ-1 (2 семестр)', 25, 2),
('ИВТ-2 (3 семестр)', 22, 3),
('ИВТ-2 (4 семестр)', 22, 4),
('ИВТ-3 (5 семестр)', 20, 5),
('ИВТ-3 (6 семестр)', 20, 6),
('ИВТ-4 (7 семестр)', 20, 7),
('ИВТ-4 (8 семестр)', 20, 8);

-- Привязка учебных групп к академическим (по курсам)
INSERT INTO study_group_academic_group (study_group_id, academic_group_id) VALUES
(1, 1),  -- 1 семестр → 1 курс
(2, 1),  -- 2 семестр → 1 курс
(3, 2),  -- 3 семестр → 2 курс
(4, 2),  -- 4 семестр → 2 курс
(5, 3),  -- 5 семестр → 3 курс
(6, 3),  -- 6 семестр → 3 курс
(7, 4),  -- 7 семестр → 4 курс
(8, 4);  -- 8 семестр → 4 курс

-- Корпуса
INSERT INTO building (name, address) VALUES
('Корпус 1', 'ул. Примерная, 1'),
('Корпус 2', 'ул. Примерная, 3');

-- Расстояния между корпусами
INSERT INTO building_distance (from_building_id, to_building_id, distance_minutes) VALUES
(1, 2, 10), (2, 1, 10);

-- Аудитории
INSERT INTO room (name, building_id, room_type, capacity) VALUES
('101', 1, 'lecture',  60),
('102', 1, 'lecture',  80),
('201', 1, 'practice', 30),
('202', 1, 'practice', 35),
('301', 2, 'lab',      20),
('302', 2, 'computer', 25),
('303', 2, 'lab',      15),
('304', 2, 'computer', 28);

-- Справочник звонков (пары)
INSERT INTO timeslot (day_of_week, pair_number, start_time, end_time)
SELECT d, p, s::TIME, e::TIME
FROM (VALUES
  (1,'08:30','10:00'), (2,'10:10','11:40'), (3,'11:50','13:20'),
  (4,'13:30','15:00'), (5,'15:10','16:40'), (6,'16:50','18:20'),
  (7,'18:30','19:00'), (8,'19:10','20:40')
) slots(p,s,e)
CROSS JOIN generate_series(1,6) d;

-- Производственный календарь: вся первая половина 2026 года (чтобы работали
-- запросы по семестрам 4 и 5) + ключевые праздники РФ
DELETE FROM work_calendar;
INSERT INTO work_calendar (calendar_date, is_working, is_holiday, note)
SELECT d::DATE,
       CASE WHEN EXTRACT(DOW FROM d::DATE) = 0 THEN FALSE ELSE TRUE END,
       CASE WHEN d::DATE IN (
           '2026-01-01','2026-01-02','2026-01-03','2026-01-04','2026-01-05',
           '2026-01-06','2026-01-08',
           '2026-02-23','2026-03-09','2026-05-01','2026-05-09',
           '2026-06-12','2026-11-04'
       ) THEN TRUE ELSE FALSE END,
       CASE
           WHEN d::DATE = '2026-01-01' THEN 'Новый год'
           WHEN d::DATE = '2026-01-07' THEN 'Рождество'
           WHEN d::DATE = '2026-02-23' THEN 'День защитника Отечества'
           WHEN d::DATE = '2026-03-08' THEN 'Международный женский день'
           WHEN d::DATE = '2026-05-01' THEN 'Праздник Весны и Труда'
           WHEN d::DATE = '2026-05-09' THEN 'День Победы'
           WHEN d::DATE = '2026-06-12' THEN 'День России'
           WHEN d::DATE = '2026-11-04' THEN 'День народного единства'
           ELSE NULL
       END
FROM generate_series('2026-01-01'::DATE, '2026-12-31'::DATE, '1 day'::INTERVAL) d;

-- Предпочтения преподавателей
DELETE FROM teacher_preference;
INSERT INTO teacher_preference (teacher_id, day_of_week, pair_number, is_preferred) VALUES
(1, 1, 1, TRUE), (1, 1, 2, TRUE), (1, 3, 1, TRUE), (1, 5, 1, FALSE),
(2, 1, 1, TRUE), (2, 1, 2, TRUE), (2, 2, 1, TRUE), (2, 2, 2, TRUE), (2, 5, 5, FALSE), (2, 5, 6, FALSE),
(3, 2, 1, TRUE), (3, 3, 1, TRUE), (3, 4, 1, TRUE), (3, 1, 1, FALSE),
(4, 1, 3, TRUE), (4, 2, 3, TRUE), (4, 3, 3, TRUE), (4, 4, 3, TRUE),
(5, 2, 2, TRUE), (5, 3, 2, TRUE), (5, 4, 2, TRUE),
(6, 1, 4, TRUE), (6, 2, 4, TRUE), (6, 3, 4, TRUE);

-- Часть 3: Шаблоны расписания по семестрам
-- Лекции — week_parity='all' (каждую неделю одинаково)
-- Практики/лабы — чередуются 'odd'/'even' (на чётной неделе одна дисциплина, на нечётной — другая)

-- Общая вспомогательная «карта преподавателей по дисциплинам», чтобы не повторять teacher_id в каждой строке
-- В шаблонах используем прямые teacher_id: 1=Иванов, 2=Петров, 3=Сидоров, 4=Кузнецова, 5=Кравцов, 6=Морозова

INSERT INTO schedule_template
    (semester_id, group_id, day_of_week, pair_number, week_parity, lesson_id, teacher_id, room_id)
SELECT v.semester_id, v.group_id, v.day_of_week, v.pair_number, v.week_parity,
       l.lesson_id, v.teacher_id, v.room_id
FROM (VALUES
    -- ============ Семестр 1, группа 1 (ИВТ-1, осень 1 курса) ============
    (1::int,1::int,1::int,1::int,'all'::varchar,  'Математический анализ',  'lecture',  1, 1),
    (1,  1, 1, 2, 'odd',  'Математический анализ', 'practice', 1, 2),
    (1,  1, 1, 2, 'even', 'Английский язык',       'practice', 4, 2),
    (1,  1, 1, 3, 'odd',  'Программирование',      'lab',      2, 8),
    (1,  1, 1, 3, 'even', 'Математический анализ', 'practice', 1, 2),
    (1,  1, 2, 1, 'all',  'Программирование',      'lecture',  2, 1),
    (1,  1, 2, 2, 'all',  'Информатика',           'lecture',  3, 1),
    (1,  1, 2, 3, 'all',  'Физика',                'lecture',  4, 2),
    (1,  1, 3, 1, 'all',  'История',               'lecture',  4, 1),
    (1,  1, 3, 2, 'odd',  'Физика',                'practice', 4, 2),
    (1,  1, 3, 2, 'even', 'Информатика',           'practice', 3, 2),
    (1,  1, 4, 1, 'odd',  'Программирование',      'lab',      2, 8),
    (1,  1, 4, 1, 'even', 'Информатика',           'practice', 3, 2),
    (1,  1, 4, 2, 'all',  'Английский язык',       'practice', 4, 2),
    (1,  1, 5, 1, 'odd',  'Физика',                'practice', 4, 2),
    (1,  1, 5, 1, 'even', 'История',               'practice', 4, 2),
    (1,  1, 5, 2, 'odd',  'История',               'practice', 4, 2),
    (1,  1, 5, 2, 'even', 'Программирование',      'consult',  2, 8),

    -- ============ Семестр 2, группа 2 (ИВТ-1, весна 1 курса) ============
    (2, 2, 1, 1, 'all',  'Математический анализ',  'lecture',  1, 1),
    (2, 2, 1, 2, 'odd',  'Математический анализ',  'practice', 1, 2),
    (2, 2, 1, 2, 'even', 'Дискретная математика',  'practice', 3, 2),
    (2, 2, 1, 3, 'odd',  'Алгоритмы и структуры данных', 'lab', 2, 6),
    (2, 2, 1, 3, 'even', 'Математический анализ',  'practice', 1, 2),
    (2, 2, 2, 1, 'all',  'Алгоритмы и структуры данных', 'lecture', 2, 1),
    (2, 2, 2, 2, 'all',  'Физика',                 'lecture',  4, 2),
    (2, 2, 2, 3, 'odd',  'Физика',                 'lab',      4, 8),
    (2, 2, 2, 3, 'even', 'Дискретная математика',  'practice', 3, 2),
    (2, 2, 3, 1, 'all',  'Дискретная математика',  'lecture',  3, 1),
    (2, 2, 3, 2, 'odd',  'Физика',                 'practice', 4, 2),
    (2, 2, 3, 2, 'even', 'Алгоритмы и структуры данных', 'lab', 2, 6),
    (2, 2, 4, 1, 'all',  'Английский язык',        'practice', 4, 2),
    (2, 2, 4, 2, 'odd',  'Физкультура',            'practice', 4, 4),
    (2, 2, 4, 2, 'even', 'Алгоритмы и структуры данных', 'consult', 2, 6),
    (2, 2, 5, 1, 'odd',  'Физика',                 'lab',      4, 8),
    (2, 2, 5, 1, 'even', 'Английский язык',        'practice', 4, 2),

    -- ============ Семестр 3, группа 3 (ИВТ-2, осень 2 курса) ============
    (3, 3, 1, 1, 'all',  'Линейная алгебра',       'lecture',  1, 1),
    (3, 3, 1, 2, 'odd',  'Линейная алгебра',       'practice', 1, 2),
    (3, 3, 1, 2, 'even', 'Базы данных',            'lab',      5, 6),
    (3, 3, 1, 3, 'all',  'Базы данных',            'lecture',  5, 1),
    (3, 3, 2, 1, 'all',  'Объектно-ориентированное программирование', 'lecture', 2, 1),
    (3, 3, 2, 2, 'all',  'Веб-разработка',         'lecture',  5, 2),
    (3, 3, 2, 3, 'odd',  'Объектно-ориентированное программирование', 'lab', 2, 6),
    (3, 3, 2, 3, 'even', 'Веб-разработка',         'lab',      5, 6),
    (3, 3, 3, 1, 'all',  'Английский язык',        'practice', 4, 2),
    (3, 3, 3, 2, 'odd',  'Базы данных',            'lab',      5, 6),
    (3, 3, 3, 2, 'even', 'Объектно-ориентированное программирование', 'lab', 2, 6),
    (3, 3, 4, 1, 'all',  'Линейная алгебра',       'lecture',  1, 1),
    (3, 3, 4, 2, 'odd',  'Веб-разработка',         'lab',      5, 6),
    (3, 3, 4, 2, 'even', 'Линейная алгебра',       'practice', 1, 2),
    (3, 3, 5, 1, 'odd',  'Объектно-ориентированное программирование', 'consult', 2, 6),
    (3, 3, 5, 1, 'even', 'Базы данных',            'lab',      5, 6),

    -- ============ Семестр 4, группа 4 (ИВТ-2, весна 2 курса) ============
    (4, 4, 1, 1, 'all',  'Теория вероятностей',    'lecture',  1, 1),
    (4, 4, 1, 2, 'odd',  'Теория вероятностей',    'practice', 1, 2),
    (4, 4, 1, 2, 'even', 'Базы данных',            'lab',      5, 6),
    (4, 4, 2, 1, 'all',  'Базы данных',            'lecture',  5, 1),
    (4, 4, 2, 2, 'all',  'Компьютерные сети',      'lecture',  5, 1),
    (4, 4, 2, 3, 'odd',  'Компьютерные сети',      'lab',      5, 6),
    (4, 4, 2, 3, 'even', 'Операционные системы',   'lab',      5, 6),
    (4, 4, 3, 1, 'all',  'Операционные системы',   'lecture',  5, 1),
    (4, 4, 3, 2, 'odd',  'Операционные системы',   'lab',      5, 6),
    (4, 4, 3, 2, 'even', 'Теория вероятностей',    'practice', 1, 2),
    (4, 4, 4, 1, 'all',  'Теория вероятностей',    'lecture',  1, 1),
    (4, 4, 4, 2, 'odd',  'Базы данных',            'lab',      5, 6),
    (4, 4, 4, 2, 'even', 'Компьютерные сети',      'lab',      5, 6),
    (4, 4, 5, 1, 'odd',  'Физкультура',            'practice', 4, 4),
    (4, 4, 5, 1, 'even', 'Операционные системы',   'lab',      5, 6),
    (4, 4, 5, 2, 'all',  'Компьютерные сети',      'lecture',  5, 1),

    -- ============ Семестр 5, группа 5 (ИВТ-3, осень 3 курса) ============
    (5, 5, 1, 1, 'all',  'Архитектура ПО',         'lecture',  3, 1),
    (5, 5, 1, 2, 'odd',  'Архитектура ПО',         'practice', 3, 2),
    (5, 5, 1, 2, 'even', 'Машинное обучение',      'lab',      6, 6),
    (5, 5, 2, 1, 'all',  'Машинное обучение',      'lecture',  6, 1),
    (5, 5, 2, 2, 'all',  'Мобильная разработка',   'lecture',  6, 2),
    (5, 5, 2, 3, 'odd',  'Мобильная разработка',   'lab',      6, 6),
    (5, 5, 2, 3, 'even', 'Архитектура ПО',         'practice', 3, 2),
    (5, 5, 3, 1, 'all',  'Математическая статистика', 'lecture', 6, 1),
    (5, 5, 3, 2, 'odd',  'Машинное обучение',      'lab',      6, 6),
    (5, 5, 3, 2, 'even', 'Математическая статистика', 'practice', 6, 2),
    (5, 5, 4, 1, 'all',  'Архитектура ПО',         'lecture',  3, 1),
    (5, 5, 4, 2, 'odd',  'Мобильная разработка',   'lab',      6, 6),
    (5, 5, 4, 2, 'even', 'Машинное обучение',      'lab',      6, 6),
    (5, 5, 5, 1, 'all',  'Английский язык',        'practice', 4, 2),
    (5, 5, 5, 2, 'odd',  'Машинное обучение',      'lab',      6, 6),
    (5, 5, 5, 2, 'even', 'Мобильная разработка',   'lab',      6, 6),

    -- ============ Семестр 6, группа 6 (ИВТ-3, весна 3 курса) ============
    (6, 6, 1, 1, 'all',  'Архитектура ПО',         'lecture',  3, 1),
    (6, 6, 1, 2, 'odd',  'Архитектура ПО',         'practice', 3, 2),
    (6, 6, 1, 2, 'even', 'DevOps и облачные технологии', 'lab', 5, 6),
    (6, 6, 2, 1, 'all',  'DevOps и облачные технологии', 'lecture', 5, 1),
    (6, 6, 2, 2, 'all',  'Машинное обучение',      'lecture',  6, 1),
    (6, 6, 2, 3, 'odd',  'DevOps и облачные технологии', 'lab', 5, 6),
    (6, 6, 2, 3, 'even', 'Машинное обучение',      'lab',      6, 6),
    (6, 6, 3, 1, 'all',  'Математическая статистика', 'lecture', 6, 1),
    (6, 6, 3, 2, 'odd',  'Машинное обучение',      'lab',      6, 6),
    (6, 6, 3, 2, 'even', 'Математическая статистика', 'practice', 6, 2),
    (6, 6, 4, 1, 'all',  'Архитектура ПО',         'lecture',  3, 1),
    (6, 6, 4, 2, 'odd',  'DevOps и облачные технологии', 'lab', 5, 6),
    (6, 6, 4, 2, 'even', 'Машинное обучение',      'lab',      6, 6),
    (6, 6, 5, 1, 'odd',  'Физкультура',            'practice', 4, 4),
    (6, 6, 5, 1, 'even', 'DevOps и облачные технологии', 'lab', 5, 6),
    (6, 6, 5, 2, 'all',  'Математическая статистика', 'lecture', 6, 1),

    -- ============ Семестр 7, группа 7 (ИВТ-4, осень 4 курса) ============
    (7, 7, 1, 1, 'all',  'Управление проектами',   'lecture',  6, 1),
    (7, 7, 1, 2, 'odd',  'Управление проектами',   'practice', 6, 2),
    (7, 7, 1, 2, 'even', 'Информационная безопасность', 'lab', 6, 6),
    (7, 7, 2, 1, 'all',  'Информационная безопасность', 'lecture', 6, 1),
    (7, 7, 2, 2, 'all',  'Распределённые системы', 'lecture',  6, 2),
    (7, 7, 2, 3, 'odd',  'Распределённые системы', 'lab',      6, 6),
    (7, 7, 2, 3, 'even', 'Информационная безопасность', 'lab', 6, 6),
    (7, 7, 3, 1, 'all',  'Управление проектами',   'lecture',  6, 1),
    (7, 7, 3, 2, 'odd',  'Информационная безопасность', 'lab', 6, 6),
    (7, 7, 3, 2, 'even', 'Управление проектами',   'practice', 6, 2),
    (7, 7, 4, 1, 'all',  'Распределённые системы', 'lecture',  6, 2),
    (7, 7, 4, 2, 'odd',  'Распределённые системы', 'lab',      6, 6),
    (7, 7, 4, 2, 'even', 'Управление проектами',   'practice', 6, 2),
    (7, 7, 5, 1, 'all',  'Английский язык',        'practice', 4, 2),
    (7, 7, 5, 2, 'odd',  'Информационная безопасность', 'lab', 6, 6),
    (7, 7, 5, 2, 'even', 'Распределённые системы', 'lab',      6, 6),

    -- ============ Семестр 8, группа 8 (ИВТ-4, весна 4 курса, диплом) ============
    (8, 8, 1, 1, 'all',  'Управление проектами',   'lecture',  6, 1),
    (8, 8, 1, 2, 'odd',  'Управление проектами',   'practice', 6, 2),
    (8, 8, 1, 2, 'even', 'Подготовка ВКР',         'consult',  6, 1),
    (8, 8, 2, 1, 'all',  'Преддипломная практика', 'internship', 6, 3),
    (8, 8, 3, 1, 'odd',  'Подготовка ВКР',         'consult',  6, 1),
    (8, 8, 3, 1, 'even', 'Управление проектами',   'practice', 6, 2),
    (8, 8, 3, 2, 'all',  'Управление проектами',   'lecture',  6, 1),
    (8, 8, 4, 1, 'odd',  'Подготовка ВКР',         'consult',  6, 1),
    (8, 8, 4, 1, 'even', 'Преддипломная практика', 'internship', 6, 3),
    (8, 8, 5, 1, 'all',  'Подготовка ВКР',         'consult',  6, 1)
) AS v(semester_id, group_id, day_of_week, pair_number, week_parity,
       subject_name, lesson_type, teacher_id, room_id)
JOIN curriculum_subject cs
  ON cs.semester_id = v.semester_id AND cs.name = v.subject_name
JOIN lesson l
  ON l.subject_id = cs.subject_id AND l.lesson_type = v.lesson_type;

-- ===== Исключения (демо) =====

-- 1. Замена преподавателя: в понедельник 2026-06-15 у ИВТ-1 (1 семестр) пара 1 — Иванов заболел,
--    вместо него ведёт Петров. Найдём нужный template_id по параметрам.
INSERT INTO schedule_exception (exception_type, template_id, entry_date, teacher_id, note)
SELECT 'replace', st.template_id, DATE '2026-06-15', 2,
       'Замена преподавателя (Иванов → Петров)'
FROM schedule_template st
JOIN curriculum_semester sm ON st.semester_id = sm.semester_id
JOIN study_group sg ON st.group_id = sg.group_id
JOIN lesson l ON st.lesson_id = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
WHERE sm.semester_number = 1 AND sg.semester_id = 1
  AND st.day_of_week = 1 AND st.pair_number = 1
  AND st.week_parity = 'all' AND cs.name = 'Математический анализ'
LIMIT 1;

-- 2. Отмена пары (пятница 12.06 — День России) у ИВТ-2 (3 семестр)
INSERT INTO schedule_exception (exception_type, template_id, entry_date, note)
SELECT 'cancel', st.template_id, DATE '2026-06-12', 'День России'
FROM schedule_template st
JOIN curriculum_semester sm ON st.semester_id = sm.semester_id
JOIN lesson l ON st.lesson_id = l.lesson_id
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
WHERE sm.semester_number = 3 AND st.day_of_week = 5 AND st.pair_number = 1
LIMIT 1;

-- 3. Доп. консультация по архитектуре ПО для ИВТ-3 (5 семестр) в среду 17.06 пара 6
INSERT INTO schedule_exception (
    exception_type, group_id, day_of_week, pair_number, week_parity, entry_date,
    lesson_id, teacher_id, room_id, note
)
SELECT 'add', 5, 3, 6, 'all', DATE '2026-06-17',
       l.lesson_id, 3, 1, 'Доп. консультация перед экзаменом'
FROM lesson l
JOIN curriculum_subject cs ON l.subject_id = cs.subject_id
JOIN curriculum_semester sm ON cs.semester_id = sm.semester_id
WHERE sm.semester_number = 5 AND cs.name = 'Архитектура ПО' AND l.lesson_type = 'consult';

-- Триггеры включены с самого начала (мы создали их в DDL), исторических нарушений нет.

