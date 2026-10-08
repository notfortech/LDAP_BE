#!/usr/bin/env python3
"""Seed the reference library with DEMONSTRATION data.

    python scripts/seed-demo-references.py "<owner-database-url>"

Why the codes below are obviously fake
--------------------------------------
Real reference entries are entered by a person who read the public
training.gov.au page for that unit, and the row records the source URL,
who entered it and when. Nothing in this system is scraped or generated.

A seed script cannot honour that. Plausible-looking codes would be worse
than useless: someone would eventually show a learner a pathway citing a
unit that does not exist, or cites one that has been superseded. So
every code here starts with DEMO and every row is marked unverified,
which makes the pathway output visibly provisional.

Replace these through the admin console before showing anyone a pathway
you intend them to act on.
"""
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

DEMO = [
    ("SK_COMMUNICATION",   "DEMOCMM401", "Make presentations"),
    ("SK_CRITICAL_THINKING","DEMOCRT402", "Apply critical thinking to work practices"),
    ("SK_DECISION_MAKING", "DEMODEC403", "Make decisions in a workplace context"),
    ("SK_COLLABORATION",   "DEMOTWK404", "Work effectively with others"),
    ("SK_ACCOUNTABILITY",  "DEMOACC405", "Take responsibility for work outcomes"),
    ("SK_ADAPTABILITY",    "DEMOADP406", "Adapt to change in the workplace"),
    ("SK_DIGITAL",         "DEMODIG407", "Use digital technologies safely"),
    ("SK_PLANNING",        "DEMOPLN408", "Plan and organise work"),
    ("SK_INITIATIVE",      "DEMOINI409", "Show initiative in a work role"),
    ("SK_ETHICS",          "DEMOETH410", "Apply professional and ethical practice"),
    ("SK_NUMERACY",        "DEMONUM411", "Interpret workplace data"),
    ("SK_CAREER",          "DEMOCAR412", "Plan a career pathway"),
]

QUALIFICATION = "DEMO40120 Certificate IV in Demonstration (NOT A REAL QUALIFICATION)"


def main(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as c:
        # Global entries live outside any tenant, and FORCE row-level
        # security applies to the owner too, so this context is required.
        c.execute(text("SELECT set_config('app.current_organisation','global',false)"))
        c.execute(text("DELETE FROM training_references WHERE unit_code LIKE 'DEMO%'"))
        for construct, code, title in DEMO:
            c.execute(text("""
                INSERT INTO training_references
                  (lineage_id, version, is_current, organisation_id, construct_id,
                   unit_code, unit_title, qualification_title, career_path,
                   training_gov_url, notes, verified, created_at)
                VALUES
                  (:lineage, 1, true, NULL, :construct,
                   :code, :title, :qual, 'Demonstration role',
                   :url,
                   'DEMONSTRATION DATA. Not a real unit of competency. Replace before use.',
                   false, :now)
            """), {
                "lineage": f"demo-{code}", "construct": construct, "code": code,
                "title": title, "qual": QUALIFICATION,
                # Built here rather than concatenated in SQL: using the
                # same bound parameter in two places with different
                # inferred types makes PostgreSQL refuse to deduce one.
                "url": f"https://training.gov.au/Training/Details/{code}",
                "now": datetime.now(timezone.utc),
            })
    print(f"Seeded {len(DEMO)} DEMONSTRATION reference entries, all marked unverified.")
    print("Pathways will now return mappings. Every one is fictional.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
