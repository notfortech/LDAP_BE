"""Request-scoped dependencies: who is calling, and which organisation
they are allowed to act on.

One rule governs this module: organisation identity is derived from the
authenticated session and the membership table, never from anything the
client sends. A client may name an organisation in the path, but naming
it only selects which of the caller's own memberships to use — it can
never grant one.
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Membership, Organisation, Role, SessionToken, User
from .security import hash_token

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request):
    return request.app.state.settings


def get_limiter(request: Request):
    return request.app.state.limiter


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, bucket: str, identity: str | None = None) -> None:
    limiter = request.app.state.limiter
    allowed, retry_after = limiter.check(bucket, identity or client_ip(request))
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_session),
) -> User:
    """Resolve the caller from an opaque bearer token.

    Every failure returns the same generic message. Distinguishing
    'expired' from 'revoked' from 'never existed' tells an attacker
    which tokens once had meaning.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")

    row = db.execute(
        select(SessionToken).where(SessionToken.token_hash == hash_token(credentials.credentials))
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    return row.user


def verified_user(user: User = Depends(current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verify your email address before performing this action.",
        )
    return user


class OrgContext:
    """A caller's validated access to one organisation."""

    def __init__(self, user: User, organisation: Organisation, role: Role):
        self.user = user
        self.organisation = organisation
        self.role = role

    @property
    def is_owner(self) -> bool:
        return self.role == Role.OWNER


def org_context(
    organisation_id: int = Path(..., ge=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> OrgContext:
    """Resolve the caller's membership of the organisation in the path.

    A non-member gets 404, not 403. 403 confirms the organisation
    exists, which lets an outsider enumerate the tenant list one id at
    a time.
    """
    membership = db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organisation_id == organisation_id,
        )
    ).scalar_one_or_none()

    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")

    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")

    return OrgContext(user=user, organisation=organisation, role=membership.role)


def require_owner(ctx: OrgContext = Depends(org_context)) -> OrgContext:
    if not ctx.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action requires the owner role")
    return ctx


def require_operating_org(ctx: OrgContext = Depends(org_context)) -> OrgContext:
    """For actions reaching outside the organisation, such as inviting a
    candidate. An unverified organisation can sign in and look around but
    cannot cause email to be sent in its name."""
    if not ctx.organisation.can_operate:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This organisation is not yet active. Verify the owner's email address first.",
        )
    return ctx
