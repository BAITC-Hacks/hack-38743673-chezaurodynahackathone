-- Catalog and provenance. List positions preserve source ordering and quotations.
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(id)) > 0),
    anon_name TEXT NOT NULL CHECK (length(trim(anon_name)) > 0),
    city TEXT NOT NULL CHECK (length(trim(city)) > 0),
    city_imputed INTEGER NOT NULL CHECK (city_imputed IN (0, 1)),
    synthetic INTEGER NOT NULL CHECK (synthetic IN (0, 1)),
    price_from_kzt INTEGER NOT NULL CHECK (price_from_kzt > 0),
    price_imputed INTEGER NOT NULL CHECK (price_imputed IN (0, 1)),
    max_hours REAL CHECK (max_hours > 0 AND max_hours <= 1.7976931348623157e308),
    description TEXT NOT NULL CHECK (length(trim(description)) >= 20),
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
    position INTEGER NOT NULL,
    PRIMARY KEY (profile_id, category)
);
CREATE TABLE IF NOT EXISTS profile_event_formats (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    event_format TEXT NOT NULL CHECK (length(trim(event_format)) > 0),
    position INTEGER NOT NULL,
    PRIMARY KEY (profile_id, event_format)
);
CREATE TABLE IF NOT EXISTS profile_languages (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    language TEXT NOT NULL CHECK (length(trim(language)) > 0),
    position INTEGER NOT NULL,
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
CREATE TABLE IF NOT EXISTS import_audit (
    id INTEGER PRIMARY KEY,
    imported_at TEXT NOT NULL,
    source_name TEXT NOT NULL,
    accepted_count INTEGER NOT NULL,
    quarantined_json TEXT NOT NULL
);
-- Local activity only. No credentials, IP addresses or browser fingerprints.
CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY NOT NULL,
    created_at TEXT NOT NULL,
    query_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_results (
    search_id TEXT NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    contractor_id TEXT NOT NULL REFERENCES profiles(id),
    position INTEGER NOT NULL CHECK (position > 0),
    PRIMARY KEY (search_id, contractor_id),
    UNIQUE (search_id, position)
);
CREATE TABLE IF NOT EXISTS selections (
    search_id TEXT NOT NULL,
    contractor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (search_id, contractor_id),
    FOREIGN KEY (search_id, contractor_id)
        REFERENCES search_results(search_id, contractor_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_searches_created ON searches(created_at);
