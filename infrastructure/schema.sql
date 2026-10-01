
CREATE TABLE members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qq TEXT,
    student_id TEXT UNIQUE,
    role TEXT NOT NULL DEFAULT 'member',
    status TEXT NOT NULL DEFAULT 'active',
    join_date TEXT,
    note TEXT
);

CREATE TABLE quota_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- 正数增加，负数消耗
    type TEXT NOT NULL,            -- init/print/contribution_reward/manual_adjust
    related_record_id INTEGER,
    operator_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    printer_name TEXT NOT NULL,
    filament_name TEXT NOT NULL,
    consumption REAL NOT NULL,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    is_charged INTEGER NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0,
    reservation_id INTEGER,
    comments TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE filaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    material TEXT,
    color TEXT,
    unit_price REAL,
    note TEXT
);

CREATE TABLE inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filament_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- 正数入库，负数出库
    type TEXT NOT NULL,            -- purchase/print/adjust
    related_record_id INTEGER,
    operator_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (filament_id) REFERENCES filaments(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE fund_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,          -- 正数收入，负数支出
    type TEXT NOT NULL,            -- income/expense
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    activity_day TEXT NOT NULL,    -- mon/wed/fri
    order_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL,            -- money/material
    material_desc TEXT,
    reward_quota REAL NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);