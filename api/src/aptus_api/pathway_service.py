"""Recommended Pathway: strongest constructs to real training products.

This is the feature the product is bought for. It converts a score into
a next step an institution can act on, naming units of competency a
learner could enrol in.

Two rules govern it, and both exist to keep the output defensible:

1. An organisation's own entry replaces the global default it forked
   from, rather than appearing alongside it. A provider customising a
   mapping means "use ours instead", not "show both".
2. Verification status travels with every mapping. A pathway never
   implies more certainty than the underlying data has.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import AssessmentAttempt, AttemptConstructScore, TrainingReference

# How many constructs a pathway is built from. Enough to give a learner
# real options, few enough that the document stays actionable.
TOP_N_CONSTRUCTS = 3


def effective_references(db: Session, organisation_id: int,
                         construct_ids: list[str]) -> dict[str, list[TrainingReference]]:
    """Current references for these constructs, with the organisation's
    forks substituted for the globals they diverged from."""
    if not construct_ids:
        return {}

    rows = db.execute(
        select(TrainingReference).where(
            TrainingReference.construct_id.in_(construct_ids),
            TrainingReference.is_current.is_(True),
            # NOT organisation_id.in_((None, organisation_id)): in SQL,
            # `col IN (NULL, 1)` is never true for a NULL column, so that
            # form silently drops every global entry.
            or_(
                TrainingReference.organisation_id.is_(None),
                TrainingReference.organisation_id == organisation_id,
            ),
        )
    ).scalars().all()

    own = [r for r in rows if r.organisation_id == organisation_id]
    # A global entry is suppressed when this organisation holds a fork of
    # it. Without this the learner sees the provider's own mapping and
    # the default it was meant to replace, side by side.
    superseded = {r.forked_from_lineage_id for r in own if r.forked_from_lineage_id}
    globals_ = [
        r for r in rows
        if r.organisation_id is None and r.lineage_id not in superseded
    ]

    grouped: dict[str, list[TrainingReference]] = {}
    for ref in own + globals_:
        grouped.setdefault(ref.construct_id, []).append(ref)
    for refs in grouped.values():
        refs.sort(key=lambda r: (r.organisation_id is None, r.unit_code))
    return grouped


def latest_formal_attempt(db: Session, candidate_id: int) -> AssessmentAttempt | None:
    return db.execute(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.candidate_id == candidate_id,
               AssessmentAttempt.mode == "formal")
        .order_by(AssessmentAttempt.created_at.desc(), AssessmentAttempt.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def build_pathway(db: Session, candidate, attempt: AssessmentAttempt) -> dict:
    scores = db.execute(
        select(AttemptConstructScore).where(AttemptConstructScore.attempt_id == attempt.id)
    ).scalars().all()

    # Ties broken by construct id so the same attempt always produces the
    # same pathway. An unstable ordering here would make the document
    # irreproducible even though the scores behind it are not.
    strongest = sorted(scores, key=lambda s: (-s.normalised, s.construct_id))[:TOP_N_CONSTRUCTS]
    grouped = effective_references(db, attempt.organisation_id, [s.construct_id for s in strongest])

    sections = []
    for sc in strongest:
        refs = grouped.get(sc.construct_id, [])
        sections.append({
            "construct_id": sc.construct_id,
            "display_name": sc.display_name,
            "score": {"normalised": sc.normalised, "band": sc.band},
            "references": [
                {
                    "unit_code": r.unit_code,
                    "unit_title": r.unit_title,
                    "qualification_title": r.qualification_title,
                    "career_path": r.career_path,
                    "training_gov_url": r.training_gov_url,
                    "verified": r.verified,
                    "source": "organisation" if r.organisation_id else "global",
                }
                for r in refs
            ],
            "reference_gap": not refs,
        })

    unverified = sum(
        1 for s in sections for r in s["references"] if not r["verified"]
    )

    return {
        "candidate_id": candidate.id,
        "attempt_id": attempt.id,
        "generated_from": {
            "engine_config_version": attempt.engine_config_version,
            "engine_config_digest": attempt.engine_config_digest,
        },
        "strongest_constructs": sections,
        # Surfaced rather than buried: a pathway built mostly on
        # unverified mappings is still useful, but the reader must be
        # told, because they may hand it to a learner.
        "unverified_reference_count": unverified,
        "constructs_without_references": [
            s["construct_id"] for s in sections if s["reference_gap"]
        ],
    }
