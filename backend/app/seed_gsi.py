"""
Real-geography seed built from GSI (Geospatial Information Authority of
Japan) open data on designated evacuation shelters / sites.

    python3 -m app.seed_gsi                       # Fukuoka City, 5 shelters
    python3 -m app.seed_gsi --city 福岡県北九州市  # another municipality

What is REAL here: shelter names, addresses and coordinates (GSI
"指定避難所" file) and which hazards the co-located designated evacuation
site covers (GSI "指定緊急避難場所" file). The GSI files contain NO capacity,
population, stock or consumption data, so those values (and warehouses,
vehicles, road segments and the storm scenario) are the same synthetic
values the Da Nang demo uses -- they are not real figures.

Users must accept GSI's terms of use (国土地理院コンテンツ利用規約) and the
usage notes shipped with the data; the data may be out of date.
"""
import argparse
import csv
import glob
import os
from . import db
from .seed import run_seed

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
DEFAULT_CITY = "福岡県福岡市"
# One shelter per ward (A..E), spread across the city.
WARDS = ["東区", "博多区", "中央区", "早良区", "西区"]
SCHOOL_WORDS = ("小学校", "中学校", "高等学校", "高校", "コミュニティ", "公民館", "センター")
HAZARDS = ("洪水", "高潮", "津波", "内水氾濫")


def _read_csv(path):
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def _find(pattern):
    hits = sorted(glob.glob(os.path.join(DATA_DIR, pattern)))
    if not hits:
        raise FileNotFoundError(f"No GSI file matching data/{pattern}. See backend/app/seed_gsi.py docstring.")
    return hits[0]


def _coord(row):
    try:
        lat, lon = float(row["緯度"]), float(row["経度"])
    except (KeyError, ValueError):
        return None
    return (lat, lon) if 20 < lat < 50 and 120 < lon < 150 else None


def select_shelters(shelters, sites, city=DEFAULT_CITY, wards=WARDS):
    """Deterministically pick one shelter per ward. Prefers schools/community
    facilities whose co-located evacuation site is flood-suitable (洪水=1)."""
    sites_by_addr = {}
    for s in sites:
        sites_by_addr.setdefault(s["住所"], s)
    chosen = []
    for ward in wards:
        prefix = city + ward
        cands = [r for r in shelters if r["住所"].startswith(prefix) and _coord(r)]
        cands.sort(key=lambda r: r["共通ID"])
        if not cands:
            raise ValueError(f"No shelters found for {prefix}")

        def score(r):
            site = sites_by_addr.get(r["住所"])
            return (
                1 if site and site.get("洪水") == "1" else 0,
                1 if any(w in r["施設・場所名"] for w in SCHOOL_WORDS) else 0,
            )
        best = max(cands, key=score)  # max() keeps the first of equals -> deterministic
        site = sites_by_addr.get(best["住所"])
        chosen.append({
            "row": best, "ward": ward,
            "hazards": [h for h in HAZARDS if site and site.get(h) == "1"] if site else [],
            "has_site": site is not None,
        })
    return chosen


def run_seed_gsi(city=DEFAULT_CITY, reset=True, shelters_csv=None, sites_csv=None):
    shelters = _read_csv(shelters_csv or _find("*_1/*_1.csv"))
    sites = _read_csv(sites_csv or _find("*_2/*_2.csv"))
    picks = select_shelters(shelters, sites, city)

    run_seed(reset=reset)  # synthetic scenario skeleton (ids, stock, vehicles, needs)
    conn = db.get_db()

    muni = city.replace("福岡県", "")
    conn.execute("UPDATE municipalities SET name=?", (f"{muni} (GSI open data, simulated scenario)",))
    conn.execute("UPDATE weather_snapshots SET region=?", ("FUKUOKA_CITY",))

    coords = []
    for letter, pick in zip("ABCDE", picks):
        row = pick["row"]
        lat, lon = _coord(row)
        coords.append((lat, lon))
        conn.execute("UPDATE shelters SET name=?, latitude=?, longitude=? WHERE shelter_id=?",
                     (row["施設・場所名"], lat, lon, f"SHELTER_{letter}"))
        # rename the synthetic access roads after the real shelter
        for suffix, label in (("PRIMARY", "primary access"), ("SECONDARY", "secondary access")):
            conn.execute("UPDATE road_segments SET name=? WHERE road_segment_id=?",
                         (f"{row['施設・場所名']} {label} (synthetic)", f"R_{letter}_{suffix}"))

    # Warehouses/vehicles are synthetic; place them at the city's shelter centroid
    # and a point between two wards so real distances/ETAs are plausible.
    clat = sum(c[0] for c in coords) / len(coords)
    clon = sum(c[1] for c in coords) / len(coords)
    wh = {"WH_01": (clat, clon, f"{muni} Central Depot (synthetic)"),
          "WH_02": ((coords[3][0] + coords[4][0]) / 2, (coords[3][1] + coords[4][1]) / 2,
                    f"{muni} West Depot (synthetic)")}
    for wid, (lat, lon, name) in wh.items():
        conn.execute("UPDATE warehouses SET name=?, latitude=?, longitude=? WHERE warehouse_id=?",
                     (name, lat, lon, wid))
        conn.execute("UPDATE vehicles SET latitude=?, longitude=? WHERE home_base_id=?", (lat, lon, wid))
    conn.commit()

    summary = []
    for letter, pick in zip("ABCDE", picks):
        r = pick["row"]
        summary.append(f"SHELTER_{letter} [{pick['ward']}] {r['施設・場所名']} ({r['共通ID']}) "
                       f"hazards={','.join(pick['hazards']) or 'n/a'}")
    db.write_audit("GSI_SEED_LOADED", actor_type="SYSTEM", state_after=db.current_state_version(),
                   explanation="GSI shelters: " + "; ".join(summary))
    print("GSI seed complete:")
    for line in summary:
        print("  " + line)
    return picks


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=DEFAULT_CITY, help="address prefix, e.g. 福岡県福岡市")
    ap.add_argument("--shelters-csv")
    ap.add_argument("--sites-csv")
    a = ap.parse_args()
    run_seed_gsi(city=a.city, shelters_csv=a.shelters_csv, sites_csv=a.sites_csv)


def real_data_available():
    return bool(glob.glob(os.path.join(DATA_DIR, "*_1", "*_1.csv"))
                and glob.glob(os.path.join(DATA_DIR, "*_2", "*_2.csv")))


def run_default_seed(reset=True):
    """Default seed for the app and tests: real GSI shelters (Fukuoka) when the
    CSVs are in <repo>/data, otherwise the synthetic demo seed.
    Set DISASTEROPS_SEED=demo to force the synthetic seed."""
    if os.environ.get("DISASTEROPS_SEED", "").lower() != "demo" and real_data_available():
        return run_seed_gsi(reset=reset)
    from . import seed
    return seed.run_seed(reset=reset)
