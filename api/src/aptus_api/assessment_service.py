"""Assessment delivery and scoring.

The API's job here is narrow: choose which items a candidate sees,
hand their responses to the engine, and persist what comes back. It
never adjusts a score, and it records the engine configuration that
produced one.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine_bridge import get_engine_config, get_item_bank, score
from .models import (
    AssessmentAttempt, AttemptConstructScore, AttemptMode, Candidate,
    CandidateAssignment,
)

# Practice is excluded from the formal record, so only the full set can
# produce an attempt that counts. This mapping is the single place that
# decision lives.
SET_MODES = {"quick": AttemptMode.PRACTICE, "full": AttemptMode.FORMAL}


def assigned_constructs(db: Session, candidate: Candidate) -> list[str] | None:
    """Returns the candidate's assigned constructs, or None for 'all'."""
    rows = db.execute(
        select(CandidateAssignment.construct_id).where(
            CandidateAssignment.candidate_id == candidate.id
        )
    ).scalars().all()
    return sorted(rows) or None


def build_assessment(db: Session, candidate: Candidate, set_id: str) -> dict:
    bank = get_item_bank()
    definition = bank.sets[set_id]
    items = bank.items_for_constructs(set_id, assigned_constructs(db, candidate))

    return {
        "set_id": set_id,
        "title": definition["title"],
        "description": definition["description"],
        "time_limit_minutes": definition.get("time_limit_minutes"),
        "counts_toward_passport": SET_MODES[set_id] is AttemptMode.FORMAL,
        "items": [
            {
                "item_id": i["question_id"],
                "situation_title": i["situation_title"],
                "background": i["background"],
                "text": i["text"],
                # Option order is the authored order. Shuffling would make
                # two candidates' assessments non-identical and break the
                # reproducibility the engine exists to provide.
                "options": i["options"],
            }
            for i in items
        ],
    }


def submit_assessment(db: Session, candidate: Candidate, set_id: str,
                      responses: dict) -> AssessmentAttempt:
    """Score responses and persist the attempt.

    Responses are filtered to the items actually served to this
    candidate. Without that, a candidate assigned four constructs could
    submit answers for all twelve and be scored on an assessment they
    were never given.
    """
    config = get_engine_config()
    served = {i["item_id"] for i in build_assessment(db, candidate, set_id)["items"]}
    filtered = {k: v for k, v in responses.items() if k in served}

    result = score(filtered, config)

    attempt = AssessmentAttempt(
        organisation_id=candidate.organisation_id,
        candidate_id=candidate.id,
        mode=SET_MODES[set_id],
        item_set=set_id,
        engine_config_version=result.config_version,
        engine_config_digest=result.config_digest,
        overall_normalised=result.overall_normalised,
        overall_band=result.overall_band,
    )
    db.add(attempt)
    db.flush()

    for construct in result.constructs:
        db.add(AttemptConstructScore(
            attempt_id=attempt.id,
            construct_id=construct.construct_id,
            display_name=construct.display_name,
            normalised=construct.normalised,
            band=construct.band,
        ))

    db.commit()
    db.refresh(attempt)
    return attempt


def passport(db: Session, candidate: Candidate) -> dict:
    """The longitudinal record: every formal attempt, oldest first.

    Practice attempts are excluded by design -- the passport is the
    institutional record, and practice explicitly does not count toward
    it.
    """
    attempts = [a for a in candidate.attempts if a.mode is AttemptMode.FORMAL]
    return {
        "candidate_id": candidate.id,
        "email": candidate.email,
        "attempt_count": len(attempts),
        "attempts": [
            {
                "attempt_id": a.id,
                "taken_at": a.created_at.isoformat() if a.created_at else None,
                "engine_config_version": a.engine_config_version,
                "engine_config_digest": a.engine_config_digest,
                "overall": {"normalised": a.overall_normalised, "band": a.overall_band},
                "constructs": [
                    {
                        "construct_id": s.construct_id,
                        "display_name": s.display_name,
                        "normalised": s.normalised,
                        "band": s.band,
                    }
                    for s in sorted(a.construct_scores, key=lambda s: s.construct_id)
                ],
            }
            for a in attempts
        ],
    }
