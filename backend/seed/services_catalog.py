"""Seed the labour catalogue with common motorcycle shop jobs.

The workbook's INFOSHEET supplies the rates KYGS already charges. This adds the
jobs a parts-and-service shop does that were not on that sheet — CVT work,
brake bleeding, electrical repairs, wheel work and so on — so the Labour &
Services tab covers a normal day at the counter.

Nothing here touches inventory: these are labour lines, priced per job, with no
stock movement.

Fees are STARTING POINTS derived from the shop's own rate card (minor jobs 50,
standard replacements 100-150, cleaning work 200-300, major work 500+). Review
them in Admin -> Services before trading on them.

    python -m backend.seed.services_catalog --dry-run
    python -m backend.seed.services_catalog
    python -m backend.seed.services_catalog --zero-fees
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.app import db  # noqa: E402

# (group, service name, suggested fee in pesos)
CATALOG = [
    # ---------------------------------------------------------------- engine
    ("Engine", "ENGINE TUNE-UP (GENERAL)", 250),
    ("Engine", "SPARK PLUG REPLACEMENT", 50),
    ("Engine", "AIR FILTER CLEANING", 50),
    ("Engine", "AIR FILTER REPLACEMENT", 50),
    ("Engine", "ENGINE OIL SEAL REPLACEMENT", 250),
    ("Engine", "CYLINDER HONING / REBORE", 500),
    ("Engine", "ENGINE FLUSHING", 100),
    ("Engine", "DECARBONIZING", 300),
    ("Engine", "COMPRESSION TEST", 100),

    # ------------------------------------------------------- CVT / drivetrain
    ("CVT & Drivetrain", "CVT OVERHAUL", 400),
    ("CVT & Drivetrain", "CVT ROLLER REPLACEMENT", 200),
    ("CVT & Drivetrain", "CVT BELT REPLACEMENT", 200),
    ("CVT & Drivetrain", "PULLEY SET REPLACEMENT", 250),
    ("CVT & Drivetrain", "CLUTCH BELL CLEANING", 150),
    ("CVT & Drivetrain", "CHAIN ADJUSTMENT", 50),
    ("CVT & Drivetrain", "CHAIN CLEANING & LUBRICATION", 80),

    # ---------------------------------------------------------------- brakes
    ("Brakes", "BRAKE FLUID CHANGE / BLEEDING", 100),
    ("Brakes", "DISC BRAKE CALIPER CLEANING", 150),
    ("Brakes", "BRAKE DISC REPLACEMENT", 150),
    ("Brakes", "BRAKE HOSE REPLACEMENT", 100),

    # --------------------------------------------------------- wheels / tires
    ("Wheels & Tires", "TIRE VULCANIZING / PATCHING", 60),
    ("Wheels & Tires", "WHEEL BALANCING", 100),
    ("Wheels & Tires", "WHEEL ALIGNMENT", 100),
    ("Wheels & Tires", "RIM REPLACEMENT", 150),
    ("Wheels & Tires", "SPOKE REPLACEMENT / TIGHTENING", 150),
    ("Wheels & Tires", "TUBELESS VALVE REPLACEMENT", 50),

    # ------------------------------------------------- suspension / chassis
    ("Suspension & Chassis", "FORK OIL CHANGE", 250),
    ("Suspension & Chassis", "REAR SHOCK ABSORBER REPLACEMENT", 150),
    ("Suspension & Chassis", "SWING ARM BUSHING REPLACEMENT", 200),
    ("Suspension & Chassis", "FRAME ALIGNMENT", 300),

    # ------------------------------------------------------------ electrical
    ("Electrical", "BATTERY CHARGING", 50),
    ("Electrical", "CHARGING SYSTEM CHECK", 100),
    ("Electrical", "STARTER MOTOR REPAIR", 300),
    ("Electrical", "STARTER MOTOR REPLACEMENT", 150),
    ("Electrical", "MAGNETO / STATOR REPLACEMENT", 300),
    ("Electrical", "SPEEDOMETER REPLACEMENT", 150),
    ("Electrical", "IGNITION SWITCH REPLACEMENT", 100),
    ("Electrical", "ALARM / IMMOBILIZER INSTALLATION", 300),

    # --------------------------------------------------------------- cooling
    ("Cooling", "COOLANT CHANGE / RADIATOR FLUSH", 150),
    ("Cooling", "RADIATOR CLEANING", 200),

    # --------------------------------------------------------- body / exhaust
    ("Body & Exhaust", "MUFFLER / EXHAUST INSTALLATION", 150),
    ("Body & Exhaust", "BODY PANEL REPLACEMENT", 150),
    ("Body & Exhaust", "WINDSHIELD INSTALLATION", 150),
    ("Body & Exhaust", "TOP BOX / CARRIER INSTALLATION", 200),

    # --------------------------------------------------------------- general
    ("General", "GENERAL CHECK-UP / INSPECTION", 100),
    ("General", "PREVENTIVE MAINTENANCE SERVICE (PMS)", 500),
    ("General", "MOTORCYCLE WASHING", 80),
    ("General", "DETAILING / FULL CLEANING", 300),
    ("General", "HOME / ROADSIDE SERVICE CHARGE", 300),
    ("General", "LABOR - INSTALLATION OF CUSTOMER PART", 100),
]


def _normalise(name: str) -> str:
    """Compare on letters and digits only, so spacing and punctuation differences
    between the workbook's wording and ours still count as the same job."""
    return "".join(ch for ch in name.upper() if ch.isalnum())


def _next_code(existing_codes) -> str:
    highest = 0
    for code in existing_codes:
        if code.upper().startswith("SVC") and code[3:].isdigit():
            highest = max(highest, int(code[3:]))
    return f"SVC{highest + 1:03d}"


def run(dry_run=False, zero_fees=False):
    db.init_db()

    rows = db.query("SELECT id, code, name FROM services")
    existing = {_normalise(r["name"]) for r in rows}
    codes = [r["code"] for r in rows]

    added, skipped = [], []
    for group, name, fee in CATALOG:
        if _normalise(name) in existing:
            skipped.append((group, name))
            continue

        added.append((group, name, 0 if zero_fees else fee))
        existing.add(_normalise(name))

        if not dry_run:
            code = _next_code(codes)
            codes.append(code)
            db.execute(
                "INSERT INTO services(code, name, fee, active) VALUES(?,?,?,1)",
                (code, name, 0 if zero_fees else fee),
            )

    return added, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be added without writing")
    parser.add_argument("--zero-fees", action="store_true",
                        help="add the jobs priced at 0 so you set every rate yourself")
    args = parser.parse_args()

    added, skipped = run(args.dry_run, args.zero_fees)

    current_group = None
    for group, name, fee in added:
        if group != current_group:
            print(f"\n  {group}")
            current_group = group
        print(f"    {name:<46} {fee:>6.2f}")

    print(f"\n{'Would add' if args.dry_run else 'Added'}: {len(added)} services")
    if skipped:
        print(f"Already present, left alone: {len(skipped)}")
    total = db.query_one("SELECT COUNT(*) AS n FROM services")["n"]
    print(f"Labour catalogue now holds: {total} services")
    if added and not args.dry_run:
        print("\nFees are starting points — review them in Admin -> Services.")


if __name__ == "__main__":
    main()
