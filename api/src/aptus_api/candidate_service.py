"""Candidate roster management: invitation, seat enforcement, assignment."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .engine_bridge import get_engine_config
from .models import Candidate, CandidateAssignment
from .security import issue_token
from .services import audit


class SeatLimitReached(Exception):
    def __init__(self, cap: int):
        self.cap = cap
        super().__init__(f"Plan limit of {cap} candidates reached")


class DuplicateCandidate(Exception):
    pass


def seat_cap(settings) -> int:
    """Free tier only for now. A subscription lookup belongs here when
    paid plans land; keeping it in one function means that change does
    not touch the invitation path."""
    return settings.free_tier_seat_cap


def count_candidates(db: Session, organisation_id: int) -> int:
    return db.execute(
        select(func.count(Candidate.id)).where(
            Candidate.organisation_id == organisation_id,
            Candidate.revoked_at.is_(None),
        )
    ).scalar_one()


def invite_candidate(db: Session, *, organisation_id: int, email: str,
                     display_name: str | None, settings, actor_user_id=None,
                     source_ip=None) -> tuple[Candidate, str]:
    """Invite a candidate and issue their access token.

    The capacity check and the insert run in one transaction. Checking
    and then inserting as separate steps lets two concurrent invitations
    both pass a check at the cap and leave the organisation one seat
    over. The unique constraint on (organisation, email) is the backstop.
    """
    email = email.lower().strip()
    cap = seat_cap(settings)

    existing = db.execute(
        select(Candidate).where(
            Candidate.organisation_id == organisation_id, Candidate.email == email
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateCandidate(email)

    if count_candidates(db, organisation_id) >= cap:
        raise SeatLimitReached(cap)

    plaintext, digest = issue_token()
    candidate = Candidate(
        organisation_id=organisation_id, email=email,
        display_name=(display_name or None), access_token_hash=digest,
    )
    db.add(candidate)
    audit(db, action="candidate.invited", organisation_id=organisation_id,
          actor_user_id=actor_user_id, target=email, source_ip=source_ip)
    db.commit()
    db.refresh(candidate)
    return candidate, plaintext


def set_assignments(db: Session, candidate: Candidate, construct_ids: list[str],
                    actor_user_id=None) -> list[str]:
    """Replace a candidate's assigned constructs.

    An unknown construct id is rejected rather than ignored: silently
    dropping one would mean an administrator believes a candidate is
    being assessed on something they are not.
    """
    known = {c["construct_id"] for c in get_engine_config().constructs}
    requested = sorted(set(construct_ids))
    unknown = [c for c in requested if c not in known]
    if unknown:
        raise ValueError(f"Unknown construct ids: {', '.join(unknown)}")

    db.query(CandidateAssignment).filter(
        CandidateAssignment.candidate_id == candidate.id
    ).delete(synchronize_session=False)
    for construct_id in requested:
        db.add(CandidateAssignment(
            candidate_id=candidate.id,
            organisation_id=candidate.organisation_id,
            construct_id=construct_id,
        ))

    audit(db, action="candidate.assignments_changed",
          organisation_id=candidate.organisation_id, actor_user_id=actor_user_id,
          target=f"{candidate.email}:{len(requested)}")
    db.commit()
    return requested
