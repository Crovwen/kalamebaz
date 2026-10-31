CREATE TABLE words (
    id          SERIAL PRIMARY KEY,
    norm        TEXT NOT NULL UNIQUE,
    display     TEXT NOT NULL,
    length      SMALLINT NOT NULL,
    letters_sig TEXT NOT NULL,
    freq        BIGINT NOT NULL DEFAULT 0,
    difficulty  SMALLINT NOT NULL DEFAULT 3 CHECK (difficulty BETWEEN 1 AND 5),
    category    TEXT NOT NULL DEFAULT 'common',
    sources     TEXT[] NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'approved',   -- approved | disabled
    puzzle_ok   BOOLEAN NOT NULL DEFAULT FALSE,     -- مناسب جواب اصلی معما
    bonus_ok    BOOLEAN NOT NULL DEFAULT TRUE,      -- مجاز به‌عنوان کلمه اضافی
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX words_sig_idx  ON words (letters_sig) WHERE status = 'approved';
CREATE INDEX words_seed_idx ON words (length, difficulty) WHERE puzzle_ok AND status = 'approved';

CREATE TABLE word_suggestions (
    id         SERIAL PRIMARY KEY,
    norm       TEXT NOT NULL,
    display    TEXT NOT NULL,
    user_id    BIGINT NOT NULL,
    chat_id    BIGINT,
    status     TEXT NOT NULL DEFAULT 'pending',     -- pending | approved | rejected
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX suggestions_status_idx ON word_suggestions (status, id);
CREATE INDEX suggestions_user_idx ON word_suggestions (user_id, created_at);

CREATE TABLE import_batches (
    id         SERIAL PRIMARY KEY,
    filename   TEXT,
    source     TEXT,
    total      INT NOT NULL,
    inserted   INT NOT NULL,
    rejected   INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id           BIGINT PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    username     TEXT,
    total_points BIGINT NOT NULL DEFAULT 0,
    words_found  INT NOT NULL DEFAULT 0,
    rounds_played INT NOT NULL DEFAULT 0,
    wins         INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX users_points_idx ON users (total_points DESC);

CREATE TABLE chats (
    id            BIGINT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    settings      JSONB NOT NULL DEFAULT '{}'::jsonb,
    round_counter INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_members (
    chat_id BIGINT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    points  BIGINT NOT NULL DEFAULT 0,
    words   INT NOT NULL DEFAULT 0,
    rounds  INT NOT NULL DEFAULT 0,
    wins    INT NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX chat_members_points_idx ON chat_members (chat_id, points DESC);

CREATE TABLE rounds (
    id           SERIAL PRIMARY KEY,
    chat_id      BIGINT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    number       INT NOT NULL,
    letters      TEXT NOT NULL,
    seed_word_id INT,
    status       TEXT NOT NULL DEFAULT 'active',     -- active | completed | time | stopped | skipped
    message_id   BIGINT,
    hints_max    INT NOT NULL DEFAULT 0,
    hints_used   INT NOT NULL DEFAULT 0,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ends_at      TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ
);
CREATE INDEX rounds_chat_idx ON rounds (chat_id, id DESC);
CREATE INDEX rounds_active_idx ON rounds (status) WHERE status = 'active';
-- در هر گروه فقط یک مرحله فعال
CREATE UNIQUE INDEX rounds_one_active_idx ON rounds (chat_id) WHERE status = 'active';

CREATE TABLE round_words (
    id          SERIAL PRIMARY KEY,
    round_id    INT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    chat_id     BIGINT NOT NULL,
    word_id     INT NOT NULL,
    norm        TEXT NOT NULL,
    display     TEXT NOT NULL,
    is_main     BOOLEAN NOT NULL,
    base_points INT NOT NULL,
    revealed    SMALLINT NOT NULL DEFAULT 0,
    points      INT NOT NULL DEFAULT 0,
    found_by    BIGINT REFERENCES users(id),
    found_at    TIMESTAMPTZ,
    UNIQUE (round_id, norm)
);
CREATE INDEX round_words_user_idx ON round_words (found_by, found_at) WHERE found_by IS NOT NULL;
CREATE INDEX round_words_recent_idx ON round_words (chat_id, round_id) WHERE is_main;

CREATE TABLE round_hints (
    id            SERIAL PRIMARY KEY,
    round_id      INT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    round_word_id INT NOT NULL,
    user_id       BIGINT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
