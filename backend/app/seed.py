"""
Seed data for DisasterOps.

Scenario: a typhoon/flood response in Da Nang, Vietnam (a fitting, real
coastal city for a Vietnam-Japan AI Hackathon disaster-response demo).
5 shelters, 2 warehouses, 5 vehicles, a handful of road segments — the
exact scale spec section 182 ("Minimum Hackathon Implementation") calls
for ("several simulated shelters ... resource inventory ... vehicle
state").

Where the spec gives concrete numbers in its own worked examples
(section 165's Example Shelter Report JSON, section 166's Example Need
Object), this seed reuses them verbatim for Shelter A's water need, so
running the live engine reproduces the spec's own scenario rather than a
disconnected fixture. Every other shelter/warehouse/vehicle value is a
plausible extrapolation of the same policy, clearly not claimed as
validated real-world data (the spec itself repeatedly makes the same
disclaimer about its prototype coefficients).
"""
import uuid
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash
from . import db


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _ago(minutes):
    return _iso(_now() - timedelta(minutes=minutes))


def _in(minutes):
    return _iso(_now() + timedelta(minutes=minutes))


def run_seed(reset=True):
    db.init_db(reset=reset)
    conn = db.get_db()

    conn.execute("INSERT INTO municipalities VALUES (?,?)",
                 ("MUNI_1", "Da Nang Coastal Emergency Management"))

    # ------------------------------------------------------------------ users
    users = [
        ("USER_V_A", "Mai Tran", "volunteer.a@disasterops.local", "VOLUNTEER", "SHELTER_A"),
        ("USER_V_B", "Huy Nguyen", "volunteer.b@disasterops.local", "VOLUNTEER", "SHELTER_B"),
        ("USER_V_C", "Lan Pham", "volunteer.c@disasterops.local", "VOLUNTEER", "SHELTER_C"),
        ("USER_V_D", "Duc Le", "volunteer.d@disasterops.local", "VOLUNTEER", "SHELTER_D"),
        ("USER_V_E", "Anh Vo", "volunteer.e@disasterops.local", "VOLUNTEER", "SHELTER_E"),
        ("USER_COORD", "Yuki Sato", "coordinator@disasterops.local", "COORDINATOR", None),
        ("USER_ADMIN", "System Admin", "admin@disasterops.local", "ADMIN", None),
    ]
    pw_hash = generate_password_hash("demo1234")
    for uid, name, email, role, shelter_id in users:
        conn.execute(
            "INSERT INTO users (user_id,name,email,password_hash,role,assigned_shelter_id,"
            "municipality_id,account_status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, name, email, pw_hash, role, shelter_id, "MUNI_1", "ACTIVE", _ago(600)),
        )

    # -------------------------------------------------------------- shelters
    # (shelter_id, name, lat, lon, pop, elderly, mobility, pregnant, young,
    #  electricity, water_supply, sanitation, mobile, primary_road, secondary_road,
    #  local_coping, last_report_source)
    shelters = [
        ("SHELTER_A", "Riverside Community Center", 16.0200, 108.2400, 82,
         12, 3, 1, 5, "NORMAL", "LIMITED", "NORMAL", "WEAK",
         "R_A_PRIMARY", "R_A_SECONDARY", "WEAK_UNVERIFIED_FALLBACK", "REGISTERED_VOLUNTEER"),
        ("SHELTER_B", "Lakeside High School Shelter", 16.0700, 108.1900, 140,
         10, 2, 0, 8, "NORMAL", "NORMAL", "NORMAL", "NORMAL",
         "R_B_PRIMARY", None, "ONE_STRONG_FALLBACK", "VERIFIED_SHELTER_MANAGER"),
        ("SHELTER_C", "Northgate Civic Hall", 16.1300, 108.1600, 55,
         8, 1, 0, 3, "FAILED", "LIMITED", "LIMITED", "WEAK",
         "R_C_PRIMARY", "R_C_SECONDARY", "PARTIAL_FALLBACK", "EMERGENCY_RESPONDER"),
        ("SHELTER_D", "Eastside Elementary Shelter", 16.0100, 108.2600, 64,
         6, 2, 1, 10, "NORMAL", "NORMAL", "NORMAL", "NORMAL",
         "R_D_PRIMARY", "R_D_SECONDARY", "WEAK_UNVERIFIED_FALLBACK", "REGISTERED_VOLUNTEER"),
        ("SHELTER_E", "Southbay Recreation Center", 15.9800, 108.2300, 45,
         4, 1, 0, 2, "NORMAL", "NORMAL", "NORMAL", "NORMAL",
         "R_E_PRIMARY", None, "ONE_STRONG_FALLBACK", "VERIFIED_SHELTER_MANAGER"),
    ]
    for (sid, name, lat, lon, pop, eld, mob, preg, young, elec, wsup, san, mob_net,
         proad, sroad, coping, source) in shelters:
        conn.execute(
            """INSERT INTO shelters
               (shelter_id, municipality_id, name, latitude, longitude, population_total,
                vulnerable_elderly, vulnerable_mobility, vulnerable_pregnant, vulnerable_young_children,
                electricity_status, water_supply_status, sanitation_status, mobile_network_status,
                primary_road_segment_id, secondary_road_segment_id, local_coping_situation,
                last_report_at, last_report_source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, "MUNI_1", name, lat, lon, pop, eld, mob, preg, young, elec, wsup, san, mob_net,
             proad, sroad, coping, _ago(8), source),
        )

    # ---------------------------------------------------------- road segments
    roads = [
        ("R_A_PRIMARY", "Riverside Bridge Road", "OPEN", "OFFICIAL_MUNICIPALITY_SYSTEM"),
        ("R_A_SECONDARY", "Riverside Levee Path", "UNKNOWN", "UNKNOWN_SOURCE"),
        ("R_B_PRIMARY", "Lakeside Boulevard", "OPEN", "OFFICIAL_MUNICIPALITY_SYSTEM"),
        ("R_C_PRIMARY", "Northgate Highway 1", "RESTRICTED", "OFFICIAL_MUNICIPALITY_SYSTEM"),
        ("R_C_SECONDARY", "Northgate Farm Road", "UNKNOWN", "UNKNOWN_SOURCE"),
        ("R_D_PRIMARY", "Eastside Coastal Road", "OPEN", "OFFICIAL_MUNICIPALITY_SYSTEM"),
        ("R_D_SECONDARY", "Eastside Inland Detour", "UNKNOWN", "UNKNOWN_SOURCE"),
        ("R_E_PRIMARY", "Southbay Access Road", "OPEN", "OFFICIAL_MUNICIPALITY_SYSTEM"),
    ]
    for rid, name, status, source in roads:
        conn.execute(
            "INSERT INTO road_segments (road_segment_id, name, status, last_updated_at, source) "
            "VALUES (?,?,?,?,?)", (rid, name, status, _ago(15), source),
        )

    # -------------------------------------------------------------- warehouses
    conn.execute("INSERT INTO warehouses VALUES (?,?,?,?,?)",
                 ("WH_01", "MUNI_1", "Central Warehouse", 16.0544, 108.2022))
    conn.execute("INSERT INTO warehouses VALUES (?,?,?,?,?)",
                 ("WH_02", "MUNI_1", "North District Warehouse", 16.1500, 108.1200))

    warehouse_inventory = [
        # warehouse, resource, on_hand, reserve, committed, unit
        ("WH_01", "WATER", 1_000_000, 200_000, 100_000, "MILLILITRE"),   # spec's own worked example
        ("WH_01", "FOOD", 3000, 300, 0, "PORTION"),
        ("WH_01", "BLANKET", 500, 50, 0, "ITEM"),
        ("WH_01", "BATTERY", 300, 30, 0, "ITEM"),
        ("WH_01", "POWER", 50, 10, 0, "HOUR_EQUIVALENT"),
        ("WH_01", "MEDICAL_SUPPLIES", 200, 20, 0, "UNIT"),
        ("WH_02", "WATER", 600_000, 150_000, 50_000, "MILLILITRE"),
        ("WH_02", "FOOD", 1500, 150, 0, "PORTION"),
        ("WH_02", "BLANKET", 250, 25, 0, "ITEM"),
        ("WH_02", "BATTERY", 150, 15, 0, "ITEM"),
        ("WH_02", "POWER", 20, 5, 0, "HOUR_EQUIVALENT"),
    ]
    for wh, rtype, onhand, reserve, committed, unit in warehouse_inventory:
        conn.execute(
            "INSERT INTO warehouse_inventory VALUES (?,?,?,?,?,?)",
            (wh, rtype, onhand, reserve, committed, unit),
        )

    # ---------------------------------------------------------------- vehicles
    vehicles = [
        # id, name, capacity(cargo-litres), unit, status, home_base, lat, lon, available_at
        ("VAN_01", "Van 1", 600, "CARGO_LITRE", "AVAILABLE", "WH_01", 16.0544, 108.2022, None),
        ("VAN_02", "Van 2", 450, "CARGO_LITRE", "ASSIGNED", "WH_01", 16.0544, 108.2022, _in(20)),
        ("VAN_03", "Van 3", 700, "CARGO_LITRE", "AVAILABLE", "WH_02", 16.1500, 108.1200, None),
        ("VAN_04", "Van 4", 500, "CARGO_LITRE", "ASSIGNED", "WH_02", 16.1500, 108.1200, _in(35)),
        ("VAN_05", "Van 5", 350, "CARGO_LITRE", "OUT_OF_SERVICE", "WH_01", 16.0544, 108.2022, None),
    ]
    for vid, name, cap, unit, status, base, lat, lon, avail in vehicles:
        conn.execute(
            "INSERT INTO vehicles (vehicle_id,name,capacity_canonical,unit,status,home_base_id,"
            "latitude,longitude,available_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (vid, name, cap, unit, status, base, lat, lon, avail),
        )

    # ------------------------------------------------------- shelter resources
    # (shelter, resource, on_hand, unit, consumption/hr, measurement, reserve, target)
    # Shelter A's WATER row intentionally reuses spec section 165/166's own
    # worked numbers: 210000 ml on hand, 80000 ml/h consumption, 500000 ml
    # target -> TTF = 210000/80000*60 = 157.5 min (spec's example: 158 min).
    resources = [
        ("SHELTER_A", "WATER", 210_000, "MILLILITRE", 80_000, "ESTIMATED", 0, 500_000),
        ("SHELTER_A", "FOOD", 390, "PORTION", 41, "COUNTED", 40, 600),
        ("SHELTER_A", "BLANKET", 95, "ITEM", 0, "COUNTED", 10, 150),
        ("SHELTER_A", "BATTERY", 32, "ITEM", 3, "COUNTED", 5, 60),

        ("SHELTER_B", "WATER", 900_000, "MILLILITRE", 50_000, "ESTIMATED", 250_000, 700_000),
        ("SHELTER_B", "FOOD", 600, "PORTION", 70, "COUNTED", 60, 500),
        ("SHELTER_B", "BLANKET", 200, "ITEM", 0, "COUNTED", 20, 150),
        ("SHELTER_B", "BATTERY", 40, "ITEM", 2, "COUNTED", 5, 35),

        ("SHELTER_C", "WATER", 150_000, "MILLILITRE", 20_000, "ESTIMATED", 15_000, 300_000),
        ("SHELTER_C", "FOOD", 250, "PORTION", 28, "COUNTED", 25, 350),
        ("SHELTER_C", "BLANKET", 60, "ITEM", 0, "COUNTED", 6, 80),
        ("SHELTER_C", "BATTERY", 15, "ITEM", 1, "COUNTED", 3, 30),
        ("SHELTER_C", "POWER", 0.4, "HOUR_EQUIVALENT", 1.0, "ESTIMATED", 0, 6),

        ("SHELTER_D", "WATER", 300_000, "MILLILITRE", 25_000, "ESTIMATED", 20_000, 350_000),
        ("SHELTER_D", "FOOD", 180, "PORTION", 35, "COUNTED", 20, 380),
        ("SHELTER_D", "BLANKET", 40, "ITEM", 0, "COUNTED", 4, 70),
        ("SHELTER_D", "BATTERY", 10, "ITEM", 1, "COUNTED", 2, 25),

        ("SHELTER_E", "WATER", 500_000, "MILLILITRE", 15_000, "ESTIMATED", 20_000, 450_000),
        ("SHELTER_E", "FOOD", 800, "PORTION", 40, "COUNTED", 50, 700),
        ("SHELTER_E", "BLANKET", 150, "ITEM", 0, "COUNTED", 15, 120),
        ("SHELTER_E", "BATTERY", 60, "ITEM", 2, "COUNTED", 6, 50),
    ]
    for sid, rtype, qty, unit, cons, meas, reserve, _target in resources:
        conn.execute(
            "INSERT INTO shelter_resources (shelter_id,resource_type,quantity_canonical,unit,"
            "consumption_per_hour_canonical,measurement,last_checked_at,reserve_quantity_canonical) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sid, rtype, qty, unit, cons, meas, _ago(8), reserve),
        )

    # ------------------------------------------------------------------ needs
    # An ACTIVE need is created wherever target > on_hand at seed time --
    # i.e. every shelter's initial reported deficit becomes a tracked need,
    # exactly as spec section 6 ("Step 4: Data Completeness") -> section 19
    # ("Comparing Active Needs") describes happening continuously in
    # production. Here we do it once at bootstrap for the demo dataset.
    for sid, rtype, qty, unit, cons, meas, reserve, target in resources:
        if target > qty:
            need_id = f"NEED_{sid[-1]}_{rtype}"
            conn.execute(
                "INSERT INTO needs (need_id, shelter_id, resource_type, unit, "
                "target_quantity_canonical, status, created_at) VALUES (?,?,?,?,?,?,?)",
                (need_id, sid, rtype, unit, target, "ACTIVE", _ago(8)),
            )

    # ------------------------------------------------------------- weather
    conn.execute(
        "INSERT INTO weather_snapshots VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), "DA_NANG_METRO", 0.10, 0.05, 1, _ago(5)),
    )

    conn.commit()
    db.write_audit("SEED_DATA_LOADED", actor_type="SYSTEM",
                    state_after=db.current_state_version(),
                    explanation="Initial Da Nang disaster-response scenario loaded.")
    print("Seed complete.")


if __name__ == "__main__":
    run_seed(reset=True)
