"""Self-serve signup, verification and sessions."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .. import services
from ..db import get_session
from ..deps import client_ip, current_user, enforce_rate_limit, get_settings
from ..models import User
from ..schemas import (
    AcceptedResponse, MeResponse, OrganisationSummary, SessionResponse,
    SigninRequest, SignupRequest, VerifyRequest,
)

router = APIRouter(tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

_SIGNUP_REPLY = (
    "If that address can be registered, a verification email is on its way. "
    "Check your inbox to activate your organisation."
)


@router.post("/auth/signup", response_model=AcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_session)):
    """Create an organisation and its owner.

    Always returns the same response whether or not the address was
    already registered. The alternative tells an unauthenticated caller
    which institutions hold accounts.
    """
    enforce_rate_limit(request, "signup")
    settings = get_settings(request)

    token = services.register_organisation(
        db, email=payload.email, password=payload.password,
        name=payload.organisation_name, rto_code=payload.rto_code,
        settings=settings, source_ip=client_ip(request),
    )

    if token is not None:
        request.app.state.email.send_verification(payload.email, token)

    if not settings.require_email_verification:
        return AcceptedResponse(detail="Organisation ready. You can sign in now.")
    return AcceptedResponse(detail=_SIGNUP_REPLY)


@router.post("/auth/verify", response_model=AcceptedResponse)
def verify(payload: VerifyRequest, request: Request, db: Session = Depends(get_session)):
    enforce_rate_limit(request, "verify")
    if not services.consume_verification(db, payload.token, source_ip=client_ip(request)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That verification link is invalid, expired, or already used.",
        )
    return AcceptedResponse(detail="Email verified. Your organisation is active.")


@router.post("/auth/signin", response_model=SessionResponse)
def signin(payload: SigninRequest, request: Request, db: Session = Depends(get_session)):
    enforce_rate_limit(request, "signin")
    settings = get_settings(request)

    user = services.authenticate(db, email=payload.email, password=payload.password)
    if user is None:
        # One message for a wrong password and an unknown address alike.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    token, expires_at = services.start_session(db, user, settings, source_ip=client_ip(request))
    return SessionResponse(token=token, expires_at=expires_at.isoformat())


@router.post("/auth/signout", response_model=AcceptedResponse)
def signout(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_session),
):
    """Revokes immediately. This is why sessions are opaque database
    rows rather than self-contained signed tokens — a signed token stays
    valid until it expires, however urgently you want it not to."""
    if credentials is not None:
        services.end_session(db, credentials.credentials)
    return AcceptedResponse(detail="Signed out.")


@router.get("/auth/me", response_model=MeResponse)
def me(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return MeResponse(
        email=user.email,
        email_verified=user.is_verified,
        organisations=[
            OrganisationSummary(
                id=o.id, name=o.name, slug=o.slug, status=o.status.value,
                rto_code=o.rto_code, role=r.value,
            )
            for o, r in services.organisations_for(db, user)
        ],
    )
