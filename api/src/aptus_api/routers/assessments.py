"""Candidate-facing assessment delivery.

Authenticated by candidate access token, never by an organisation
membership. A candidate can reach exactly one candidate's assessment:
their own.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import assessment_service
from ..db import get_session
from ..deps import current_candidate, enforce_rate_limit
from ..engine_bridge import get_item_bank

router = APIRouter(prefix="/assessment", tags=["assessment"])


class SubmitRequest(BaseModel):
    # item_id -> selected option. Capped so a single request cannot be
    # used to push unbounded data at the scorer.
    responses: dict[str, str] = Field(max_length=200)


@router.get("/{set_id}")
def get_assessment(set_id: str, candidate=Depends(current_candidate),
                   db: Session = Depends(get_session)):
    if set_id not in get_item_bank().sets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown assessment set")
    return assessment_service.build_assessment(db, candidate, set_id)


@router.post("/{set_id}/submit")
def submit(set_id: str, payload: SubmitRequest, request: Request,
           candidate=Depends(current_candidate), db: Session = Depends(get_session)):
    if set_id not in get_item_bank().sets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown assessment set")
    enforce_rate_limit(request, "public", identity=f"candidate:{candidate.id}")

    try:
        attempt = assessment_service.submit_assessment(db, candidate, set_id, payload.responses)
    except Exception as exc:  # engine rejects an option outside the scale
        from aptus_engine import ResponseError
        if isinstance(exc, ResponseError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        raise

    return {
        "attempt_id": attempt.id,
        "mode": attempt.mode.value,
        "counts_toward_passport": attempt.mode.value == "formal",
        "overall": {"normalised": attempt.overall_normalised, "band": attempt.overall_band},
        "constructs": [
            {"construct_id": s.construct_id, "display_name": s.display_name,
             "normalised": s.normalised, "band": s.band}
            for s in sorted(attempt.construct_scores, key=lambda s: s.construct_id)
        ],
        "engine_config_version": attempt.engine_config_version,
    }
