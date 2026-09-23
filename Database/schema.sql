-- Профили и происхождение данных. Коллекции хранятся в связанных таблицах.
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(id)) > 0),
    anon_name TEXT NOT NULL CHECK (length(trim(anon_name)) > 0),
    city TEXT NOT NULL CHECK (length(trim(city)) > 0),
    city_imputed INTEGER NOT NULL CHECK (city_imputed IN (0, 1)),
    synthetic INTEGER NOT NULL CHECK (synthetic IN (0, 1)),
    price_from_kzt INTEGER NOT NULL CHECK (price_from_kzt > 0),
    price_imputed INTEGER NOT NULL CHECK (price_imputed IN (0, 1)),
    max_hours REAL CHECK (max_hours > 0),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    experience_years INTEGER CHECK (experience_years >= 0),
    calendar_start TEXT NOT NULL,
    calendar_end TEXT NOT NULL CHECK (calendar_end >= calendar_start),
    source_type TEXT NOT NULL CHECK (source_type IN ('csv', 'generated')),
    source_name TEXT NOT NULL,
    CHECK (source_type != 'generated' OR synthetic = 1)
);

CREATE TABLE IF NOT EXISTS profile_categories (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (length(trim(category)) > 0),
    PRIMARY KEY (profile_id, category)
);
CREATE TABLE IF NOT EXISTS profile_event_formats (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    event_format TEXT NOT NULL CHECK (length(trim(event_format)) > 0),
    PRIMARY KEY (profile_id, event_format)
);
CREATE TABLE IF NOT EXISTS profile_languages (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    language TEXT NOT NULL CHECK (length(trim(language)) > 0),
    PRIMARY KEY (profile_id, language)
);
CREATE TABLE IF NOT EXISTS profile_busy_dates (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    busy_date TEXT NOT NULL,
    PRIMARY KEY (profile_id, busy_date)
);

CREATE INDEX IF NOT EXISTS idx_profiles_city_price ON profiles(city, price_from_kzt);
CREATE INDEX IF NOT EXISTS idx_categories_value ON profile_categories(category, profile_id);
CREATE INDEX IF NOT EXISTS idx_formats_value ON profile_event_formats(event_format, profile_id);
CREATE INDEX IF NOT EXISTS idx_languages_value ON profile_languages(language, profile_id);
CREATE INDEX IF NOT EXISTS idx_busy_dates_value ON profile_busy_dates(busy_date, profile_id);

-- Удобный вход для существующих модулей: списки собраны в строки через «|».
CREATE VIEW IF NOT EXISTS profiles_for_ranking AS
SELECT p.*,
    (SELECT group_concat(category, '|') FROM
        (SELECT category FROM profile_categories WHERE profile_id = p.id ORDER BY category)) AS categories,
    (SELECT group_concat(event_format, '|') FROM
        (SELECT event_format FROM profile_event_formats WHERE profile_id = p.id ORDER BY event_format)) AS event_formats,
    (SELECT group_concat(language, '|') FROM
        (SELECT language FROM profile_languages WHERE profile_id = p.id ORDER BY language)) AS languages,
    COALESCE((SELECT group_concat(busy_date, '|') FROM
        (SELECT busy_date FROM profile_busy_dates WHERE profile_id = p.id ORDER BY busy_date)), '') AS busy_dates
FROM profiles p;
