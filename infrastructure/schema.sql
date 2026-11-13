
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qq TEXT,
    student_id TEXT UNIQUE,
    role TEXT NOT NULL DEFAULT 'member',
    status TEXT NOT NULL DEFAULT 'active',
    join_date TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    printer_name TEXT NOT NULL,
    filament_name TEXT NOT NULL,
    consumption REAL NOT NULL,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    reservation_id INTEGER,
    comments TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
