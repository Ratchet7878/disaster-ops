"""
DisasterOps persistence layer.

Uses Python's built-in sqlite3 (no ORM dependency needed/available in this
environment). Table set follows spec section 169 "Database Tables" and
section 170 "Core Database Relationships" as closely as an MVP allows.
"""
import sqlite3
import os
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "disasterops.db")

_local = threading.local()


def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return _local.conn


def close_db(*_args):
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


SCHEMA = """
-- Global monotonically-increasing operational state version (spec 144.2, 171)
CREATE TABLE IF NOT EXISTS state_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS municipalities (
    municipality_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('VOLUNTEER','SHELTER_MANAGER','COORDINATOR','ADMIN','DRIVER')),
    assigned_shelter_id TEXT,
    municipality_id TEXT,
    account_status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS shelters (
    shelter_id TEXT PRIMARY KEY,
    municipality_id TEXT,
    name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    population_total INTEGER NOT NULL DEFAULT 0,
    vulnerable_elderly INTEGER NOT NULL DEFAULT 0,
    vulnerable_mobility INTEGER NOT NULL DEFAULT 0,
    vulnerable_pregnant INTEGER NOT NULL DEFAULT 0,
    vulnerable_young_children INTEGER NOT NULL DEFAULT 0,
    electricity_status TEXT NOT NULL DEFAULT 'NORMAL',
    water_supply_status TEXT NOT NULL DEFAULT 'NORMAL',
    sanitation_status TEXT NOT NULL DEFAULT 'NORMAL',
    mobile_network_status TEXT NOT NULL DEFAULT 'NORMAL',
    primary_road_segment_id TEXT,
    secondary_road_segment_id TEXT,
    local_coping_situation TEXT NOT NULL DEFAULT 'NONE',
    last_report_at TEXT,
    last_report_source TEXT NOT NULL DEFAULT 'UNKNOWN_SOURCE'
);

CREATE TABLE IF NOT EXISTS shelter_reports (
    report_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    shelter_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'HOURLY',   -- HOURLY | CRITICAL_UPDATE
    payload_json TEXT NOT NULL,
    state_version_after INTEGER,
    source TEXT NOT NULL DEFAULT 'REGISTERED_VOLUNTEER'
);

-- shelter_resources = current on-hand inventory per shelter+resource type
CREATE TABLE IF NOT EXISTS shelter_resources (
    shelter_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    quantity_canonical REAL,          -- NULL = unknown (never coerce to 0)
    unit TEXT NOT NULL,
    consumption_per_hour_canonical REAL,
    measurement TEXT NOT NULL DEFAULT 'ESTIMATED',
    last_checked_at TEXT,
    reserve_quantity_canonical REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (shelter_id, resource_type)
);

CREATE TABLE IF NOT EXISTS resource_requests (
    request_id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    quantity_requested_canonical REAL NOT NULL,
    reason TEXT,
    human_perceived_urgency TEXT,     -- LOW|MEDIUM|HIGH|CRITICAL (advisory only)
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id TEXT PRIMARY KEY,
    municipality_id TEXT,
    name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse_inventory (
    warehouse_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    quantity_on_hand_canonical REAL NOT NULL,
    reserve_quantity_canonical REAL NOT NULL DEFAULT 0,
    committed_quantity_canonical REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL,
    PRIMARY KEY (warehouse_id, resource_type)
);

CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capacity_canonical REAL NOT NULL,
    unit TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'AVAILABLE',   -- AVAILABLE|ASSIGNED|IN_TRANSIT|OUT_OF_SERVICE|UNKNOWN
    home_base_id TEXT,                          -- warehouse_id it starts from
    latitude REAL,
    longitude REAL,
    available_at TEXT                           -- if busy, when it frees up
);

CREATE TABLE IF NOT EXISTS road_segments (
    road_segment_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN|RESTRICTED|BLOCKED|UNKNOWN
    last_updated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'OFFICIAL_MUNICIPALITY_SYSTEM'
);

CREATE TABLE IF NOT EXISTS road_events (
    event_id TEXT PRIMARY KEY,
    road_segment_id TEXT NOT NULL,
    new_status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS weather_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    weather_risk REAL NOT NULL,     -- Wr in [0,1]
    obstruction_risk REAL NOT NULL, -- Or in [0,1]
    travel_allowed INTEGER NOT NULL DEFAULT 1,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS needs (
    need_id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    unit TEXT NOT NULL,
    target_quantity_canonical REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE|STABILIZED|FULFILLED|CANCELLED
    created_at TEXT NOT NULL,
    last_urgency_json TEXT,
    last_urgency_state_version INTEGER
);

CREATE TABLE IF NOT EXISTS candidate_plans (
    candidate_id TEXT PRIMARY KEY,
    planning_run_id TEXT NOT NULL,
    need_id TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    generation_pattern TEXT NOT NULL,
    plan_json TEXT NOT NULL,           -- full CandidatePlan contract, serialized
    feasibility_json TEXT,
    utility_json TEXT,
    status TEXT NOT NULL DEFAULT 'GENERATED',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY,
    planning_run_id TEXT NOT NULL,
    need_id TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    recommended_candidate_id TEXT,
    no_acceptable_plan INTEGER NOT NULL DEFAULT 0,
    ranking_json TEXT NOT NULL,
    explanation_json TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'  -- PENDING_APPROVAL|APPROVED|MODIFIED|REJECTED|EXPIRED|SUPERSEDED
);

CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    need_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    source_type TEXT NOT NULL,      -- WAREHOUSE | SHELTER
    source_id TEXT NOT NULL,
    destination_shelter_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    quantity_canonical REAL NOT NULL,
    unit TEXT NOT NULL,
    depart_at TEXT NOT NULL,
    eta_minutes REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'DISPATCHED',  -- DISPATCHED|IN_TRANSIT|DELAYED|DELIVERED|CANCELLED
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    actual_quantity_received REAL,
    damaged_or_missing REAL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL,
    decision TEXT NOT NULL,     -- APPROVE|MODIFY|REJECT
    actor_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,   -- HUMAN|SYSTEM|AGENT|EXTERNAL_SERVICE
    actor_id TEXT,
    occurred_at TEXT NOT NULL,
    state_version_before INTEGER,
    state_version_after INTEGER,
    object_id TEXT,
    reason_codes TEXT,
    explanation TEXT
);
"""


def init_db(reset=False):
    if reset:
        close_db()  # drop any open connection to the file we're about to delete
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = get_db()
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT version FROM state_version WHERE id = 1")
    if cur.fetchone() is None:
        conn.execute("INSERT INTO state_version (id, version) VALUES (1, 1)")
    conn.commit()


def bump_state_version():
    """Atomically increments and returns the new global state version."""
    conn = get_db()
    conn.execute("UPDATE state_version SET version = version + 1 WHERE id = 1")
    row = conn.execute("SELECT version FROM state_version WHERE id = 1").fetchone()
    conn.commit()
    return row["version"]


def current_state_version():
    conn = get_db()
    row = conn.execute("SELECT version FROM state_version WHERE id = 1").fetchone()
    return row["version"] if row else 1


def write_audit(event_type, actor_type="SYSTEM", actor_id=None, object_id=None,
                 state_before=None, state_after=None, reason_codes=None, explanation=None):
    import uuid
    from datetime import datetime, timezone
    conn = get_db()
    conn.execute(
        """INSERT INTO audit_logs
           (event_id, event_type, actor_type, actor_id, occurred_at,
            state_version_before, state_version_after, object_id, reason_codes, explanation)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), event_type, actor_type, actor_id,
         datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
         state_before, state_after, object_id,
         ",".join(reason_codes) if reason_codes else None, explanation),
    )
    conn.commit()
