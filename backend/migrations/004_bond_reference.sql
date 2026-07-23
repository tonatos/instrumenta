-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS bond_credit_ratings (
    isin        VARCHAR(16) PRIMARY KEY,
    rating      TEXT NOT NULL,
    source      VARCHAR(16) NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bond_default_flags (
    isin                    VARCHAR(16) PRIMARY KEY,
    has_default             BOOLEAN NOT NULL DEFAULT FALSE,
    has_technical_default   BOOLEAN NOT NULL DEFAULT FALSE,
    source                  VARCHAR(16) NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS issuer_rating_patterns (
    pattern     TEXT PRIMARY KEY,
    rating      TEXT NOT NULL
);

INSERT INTO issuer_rating_patterns (pattern, rating) VALUES
    ('ОФЗ', 'ruAAA'),
    ('ДОМ.РФ', 'ruAAA'),
    ('ДомРФ', 'ruAAA'),
    ('ДОМРФ', 'ruAAA'),
    ('ВЭБ', 'ruAAA'),
    ('РСХБ', 'ruAAA'),
    ('Россельхоз', 'ruAAA'),
    ('РЖД', 'ruAAA'),
    ('Сбер', 'ruAAA'),
    ('Газпром', 'ruAA+'),
    ('ГПБ', 'ruAA+'),
    ('ALFAB', 'ruAA+'),
    ('АЛЬФАБ', 'ruAA+'),
    ('ВТБ', 'ruAA+'),
    ('Роснефт', 'ruAA+'),
    ('ЛУКОЙЛ', 'ruAA+'),
    ('Транснефт', 'ruAA+'),
    ('НОВАТЭК', 'ruAA'),
    ('Норник', 'ruAA'),
    ('ГМКНОРНК', 'ruAA'),
    ('СевСтал', 'ruAA'),
    ('Северст', 'ruAA'),
    ('Алроса', 'ruAA'),
    ('АЛРОСА', 'ruAA'),
    ('Тинькоф', 'ruAA'),
    ('ТБАНК', 'ruAA'),
    ('ТBANK', 'ruAA'),
    ('TCS', 'ruAA'),
    ('ВБРР', 'ruAA'),
    ('СовкомБ', 'ruAA-'),
    ('ПСБ', 'ruA+'),
    ('Промсвяз', 'ruA+'),
    ('Х5', 'ruAA-'),
    ('ИКС5', 'ruAA-'),
    ('X5 Retail', 'ruAA-'),
    ('МТС', 'ruA+'),
    ('Ростел', 'ruA+'),
    ('Магнит', 'ruA+'),
    ('Пятёроч', 'ruA+'),
    ('ПочтаБанк', 'ruA+'),
    ('МКБ', 'ruA'),
    ('МосКред', 'ruA'),
    ('Систем', 'ruA-'),
    ('Русал', 'ruA'),
    ('РУСАЛ', 'ruA'),
    ('ОКЕЙ', 'ruBBB-'),
    ('О''КЕЙ', 'ruBBB-'),
    ('М.видео', 'ruBB+'),
    ('Мвидео', 'ruBB+'),
    ('МВИДЕО', 'ruBB+'),
    ('Этал', 'ruBBB'),
    ('ЛСР', 'ruA-'),
    ('ПИК', 'ruA-'),
    ('Аэрофл', 'ruA-'),
    ('АЭРОФЛ', 'ruA-'),
    ('Детски мир', 'ruA-'),
    ('ДетМир', 'ruA-'),
    ('ГТЛК', 'ruAA-'),
    ('Сегеж', 'ruCC'),
    ('СЕГЕЖ', 'ruCC')
ON CONFLICT (pattern) DO NOTHING;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS issuer_rating_patterns;
DROP TABLE IF EXISTS bond_default_flags;
DROP TABLE IF EXISTS bond_credit_ratings;
-- +goose StatementEnd
