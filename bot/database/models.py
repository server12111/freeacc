from dataclasses import dataclass
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER UNIQUE NOT NULL,
    username    TEXT,
    first_name  TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts_pool (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'free',
    added_by    INTEGER,
    added_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_tg_id         INTEGER NOT NULL,
    channel_id          TEXT NOT NULL,
    participant_number  INTEGER NOT NULL DEFAULT 0,
    piarflow_msg_id     INTEGER,
    piarflow_link       TEXT,
    invite_threshold    INTEGER NOT NULL DEFAULT 10,
    invite_count        INTEGER NOT NULL DEFAULT 0,
    invite_count_offset INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at         DATETIME,
    launched_at         DATETIME,
    milestone_10        INTEGER NOT NULL DEFAULT 0,
    milestone_20        INTEGER NOT NULL DEFAULT 0,
    milestone_30        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS issued_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id         INTEGER NOT NULL REFERENCES accounts_pool(id),
    user_tg_id      INTEGER NOT NULL,
    user_username   TEXT,
    contest_id      INTEGER REFERENCES contests(id),
    issued_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    details     TEXT,
    admin_tg_id INTEGER,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_tg_id  INTEGER NOT NULL,
    invoice_id  TEXT NOT NULL UNIQUE,
    amount      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    pool_id     INTEGER REFERENCES accounts_pool(id),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    paid_at     DATETIME
);

CREATE TABLE IF NOT EXISTS referrals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_tg_id  INTEGER NOT NULL,
    referee_tg_id   INTEGER NOT NULL UNIQUE,
    won             INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'free',
    issued_to   INTEGER,
    added_by    INTEGER,
    added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    issued_at   DATETIME
);

CREATE TABLE IF NOT EXISTS referral_rewards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_tg_id  INTEGER NOT NULL UNIQUE,
    pool_id     INTEGER REFERENCES accounts_pool(id),
    issued_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ads_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    url        TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('parse_pattern', ''),
    ('notify_text', 'Поздравляем! Вы выполнили условие конкурса.\n\nВаш аккаунт:\n{account}'),
    ('tutorial_text', '📖 <b>Как получить аккаунт бесплатно:</b>\n\n1️⃣ Нажми «Получить бесплатно»\n2️⃣ Получи личную реферальную ссылку\n3️⃣ Поделись ей с друзьями\n4️⃣ Когда наберёшь 10 участников — аккаунт придёт автоматически\n\nВсё просто! 🚀'),
    ('tutorial_video_id', ''),
    ('require_subscription', '0'),
    ('reviews_url', ''),
    ('contest_start_time', ''),
    ('contest_end_time', ''),
    ('promo_low_stock_alert', '5'),
    ('account_low_stock_alert', '3'),
    ('reviews_channel_id', '');
"""


@dataclass
class User:
    id: int
    tg_id: int
    username: Optional[str]
    first_name: Optional[str]
    created_at: str


@dataclass
class AccountPool:
    id: int
    data: str
    status: str
    added_by: Optional[int]
    added_at: str


@dataclass
class Contest:
    id: int
    owner_tg_id: int
    channel_id: str
    participant_number: int
    piarflow_msg_id: Optional[int]
    piarflow_link: Optional[str]
    invite_threshold: int
    invite_count: int
    status: str
    created_at: str
    finished_at: Optional[str]
    launched_at: Optional[str]
    milestone_10: int = 0
    milestone_20: int = 0
    milestone_30: int = 0
    invite_count_offset: int = 0


@dataclass
class IssuedAccount:
    id: int
    pool_id: int
    user_tg_id: int
    user_username: Optional[str]
    contest_id: Optional[int]
    issued_at: str


@dataclass
class Purchase:
    id: int
    user_tg_id: int
    invoice_id: str
    amount: str
    status: str
    pool_id: Optional[int]
    created_at: str
    paid_at: Optional[str]


@dataclass
class Referral:
    id: int
    referrer_tg_id: int
    referee_tg_id: int
    won: int
    created_at: str


@dataclass
class PromoCode:
    id: int
    code: str
    status: str
    issued_to: Optional[int]
    added_by: Optional[int]
    added_at: str
    issued_at: Optional[str]


@dataclass
class ReferralReward:
    id: int
    user_tg_id: int
    pool_id: Optional[int]
    issued_at: str


@dataclass
class AdsItem:
    id: int
    type: str
    name: str
    text: str
    created_at: str
