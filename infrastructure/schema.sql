
-- 建表脚本，只在空库上执行（见 infrastructure/db.py 的 _init_schema）。
-- 结构版本：2 —— 与 db.py 的 SCHEMA_VERSION 保持一致；改动本文件必须同步 +1。

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
    amount REAL NOT NULL,         
    type TEXT NOT NULL,        
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
    filament_id INTEGER NOT NULL,
    filament_name TEXT NOT NULL,
    consumption REAL NOT NULL,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    reservation_id INTEGER,
    comments TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id),
    FOREIGN KEY (filament_id) REFERENCES filaments(id)
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
    amount REAL NOT NULL,        
    type TEXT NOT NULL,         
    related_record_id INTEGER,
    operator_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (filament_id) REFERENCES filaments(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE fund_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,      
    type TEXT NOT NULL,        
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

CREATE TABLE reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    activity_day TEXT NOT NULL,  
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
    type TEXT NOT NULL,           
    material_desc TEXT,
    reward_quota REAL NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);

-- 索引（阶段 1 新增）：额度 / 库存 / 经费余额都是 SUM 聚合，按维度建索引
CREATE INDEX ix_records_member       ON records(member_id);
CREATE INDEX ix_records_date         ON records(date);
CREATE INDEX ix_records_filament     ON records(filament_id);
CREATE INDEX ix_quota_member         ON quota_transactions(member_id);
CREATE INDEX ix_inventory_filament   ON inventory_transactions(filament_id);
CREATE INDEX ix_fund_date            ON fund_transactions(date);
CREATE INDEX ix_contributions_member ON contributions(member_id);
CREATE INDEX ix_reservations_week    ON reservations(week_start, activity_day);
