
-- 建表脚本，只在空库上执行（见 infrastructure/db.py 的 _init_schema）。
-- 结构版本：6 —— 与 db.py 的 SCHEMA_VERSION 保持一致；改动本文件必须同步 +1。

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
    order_no INTEGER NOT NULL DEFAULT 0,          -- 0 = 未排班；审核通过时分配 1..n
    status TEXT NOT NULL DEFAULT 'pending',       -- pending / approved / rejected / cancelled
    operator_id INTEGER NOT NULL,                 -- 提交人
    reviewer_id INTEGER,                          -- 审核（或撤销）的人
    reviewed_at TEXT,                             -- 审核时间
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id),
    FOREIGN KEY (reviewer_id) REFERENCES members(id)
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

-- 登录账号（阶段 2.2 新增）：权限取自关联社员的 role
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    member_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

-- 索引（阶段 1 新增）：额度 / 库存 / 经费余额都是 SUM 聚合，按维度建索引
CREATE INDEX ix_records_member       ON records(member_id);
CREATE INDEX ix_records_date         ON records(date);
CREATE INDEX ix_records_filament     ON records(filament_id);
CREATE INDEX ix_quota_member         ON quota_transactions(member_id);
CREATE INDEX ix_inventory_filament   ON inventory_transactions(filament_id);
CREATE INDEX ix_fund_date            ON fund_transactions(date);
CREATE INDEX ix_contributions_member ON contributions(member_id);

-- 全局配置（阶段 3.2 新增）：键值对，目前放 low_stock_threshold（低库存阈值，单位克）
CREATE TABLE settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    note TEXT
);

-- 站内通知（阶段 3.2 新增）：member_id = 收件人；ref 指向关联对象，例如 "filament:1"
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    ref TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX ix_notifications_member ON notifications(member_id, read_at);

-- 打印机（阶段 3.3）：社团 3 台机器，老师也会用；
-- status：idle 空闲 / in_use 使用中（used_by + expected_end）/ maintenance 维修中
CREATE TABLE printers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    used_by INTEGER,
    expected_end TEXT,
    note TEXT,
    updated_at TEXT,
    updated_by INTEGER,
    FOREIGN KEY (used_by) REFERENCES members(id),
    FOREIGN KEY (updated_by) REFERENCES members(id)
);
CREATE INDEX ix_printers_status ON printers(status);

-- 预约（阶段 2.3 新增）：提交不设限，只有「已通过」才进排班表；
-- 部分唯一索引保证同一天同一人最多一条已通过的排班（待审核 / 被驳回的不受限制）
CREATE UNIQUE INDEX ux_reservations_approved
    ON reservations(week_start, activity_day, member_id) WHERE status = 'approved';
CREATE INDEX ix_reservations_schedule
    ON reservations(week_start, activity_day, status, order_no);
