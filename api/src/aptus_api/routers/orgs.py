"""Organisation-scoped endpoints.

Every route carries {organisation_id} and resolves it through
org_context, which checks membership. The path selects among the
caller's own organisations; it never grants access to one.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import assessment_service, candidate_service, pathway_service
from ..db import get_session
from ..deps import (
    OrgContext, candidate_in_org, client_ip, enforce_rate_limit, get_settings,
    org_context, require_operating_org,
)
from ..engine_bridge import get_engine_config
from ..models import Candidate

router = APIRouter(prefix="/orgs/{organisation_id}", tags=["organisations"])


class InviteRequest(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)


class AssignmentRequest(BaseModel):
    construct_ids: list[str] = Field(max_length=50)


def _candidate_summary(c: Candidate) -> dict:
    formal = [a for a in c.attempts if a.mode.value == "formal"]
    latest = formal[-1] if formal else None
    return {
        "id": c.id,
        "email": c.email,
        "display_name": c.display_name,
        "invited_at": c.invited_at.isoformat() if c.invited_at else None,
        "formal_attempts": len(formal),
        "latest_result": (
            {"normalised": latest.overall_normalised, "band": latest.overall_band}
            if latest else None
        ),
    }


@router.get("")
def get_organisation(ctx: OrgContext = Depends(org_context)):
    org = ctx.organisation
    return {
        "id": org.id, "name": org.name, "slug": org.slug,
        "status": org.status.value, "rto_code": org.rto_code,
        "your_role": ctx.role.value, "can_operate": org.can_operate,
    }


@router.get("/candidates")
def list_candidates(request: Request, ctx: OrgContext = Depends(org_context),
                    db: Session = Depends(get_session)):
    rows = db.execute(
        select(Candidate)
        .where(Candidate.organisation_id == ctx.organisation.id,
               Candidate.revoked_at.is_(None))
        .order_by(Candidate.id)
    ).scalars().all()
    return {
        "organisation_id": ctx.organisation.id,
        "seat_cap": candidate_service.seat_cap(get_settings(request)),
        "seats_used": candidate_service.count_candidates(db, ctx.organisation.id),
        "candidates": [_candidate_summary(c) for c in rows],
    }


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
def invite_candidate(payload: InviteRequest, request: Request,
                     ctx: OrgContext = Depends(require_operating_org),
                     db: Session = Depends(get_session)):
    enforce_rate_limit(request, "invite", identity=f"org:{ctx.organisation.id}")
    try:
        candidate, access_token = candidate_service.invite_candidate(
            db, organisation_id=ctx.organisation.id, email=payload.email,
            display_name=payload.display_name, settings=get_settings(request),
            actor_user_id=ctx.user.id, source_ip=client_ip(request),
        )
    except candidate_service.DuplicateCandidate:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This candidate has already been invited.") from None
    except candidate_service.SeatLimitReached as exc:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"Your plan allows {exc.cap} candidates. Upgrade to invite more.",
        ) from None

    # The access token is returned once, here. It is stored only as a
    # digest, so this response is the sole opportunity to deliver it.
    return {**_candidate_summary(candidate), "access_token": access_token}


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate=Depends(candidate_in_org), db: Session = Depends(get_session)):
    return {
        **_candidate_summary(candidate),
        "assigned_constructs": assessment_service.assigned_constructs(db, candidate) or [],
        "passport": assessment_service.passport(db, candidate),
    }


@router.put("/candidates/{candidate_id}/assignments")
def set_assignments(payload: AssignmentRequest, ctx: OrgContext = Depends(org_context),
                    candidate=Depends(candidate_in_org), db: Session = Depends(get_session)):
    try:
        assigned = candidate_service.set_assignments(
            db, candidate, payload.construct_ids, actor_user_id=ctx.user.id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return {"candidate_id": candidate.id, "assigned_constructs": assigned}


@router.get("/candidates/{candidate_id}/pathway")
def get_pathway(candidate=Depends(candidate_in_org), db: Session = Depends(get_session)):
    """The Recommended Pathway for a candidate's most recent formal
    attempt. Practice runs never produce one -- a pathway handed to a
    learner must come from the assessment that counts."""
    attempt = pathway_service.latest_formal_attempt(db, candidate.id)
    if attempt is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This candidate has not completed a full assessment yet.",
        )
    return pathway_service.build_pathway(db, candidate, attempt)


@router.get("/constructs")
def list_constructs(ctx: OrgContext = Depends(org_context)):
    """The capability constructs available for assignment, with the
    evidence metadata the engine carries for each."""
    return {
        "engine_config_version": get_engine_config().version,
        "constructs": [
            {
                "construct_id": c["construct_id"],
                "display_name": c["display_name"],
                "definition": c["definition"],
                "mapping_strength": c["evidence"]["mapping_strength"],
            }
            for c in get_engine_config().constructs
        ],
    }
