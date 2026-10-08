"""Self-serve signup and session issuance.

Kept out of the router so the ordering guarantees below are testable
without an HTTP client, and so the router stays a thin translation of
HTTP to domain calls.
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent, EmailVerification, Membership, Organisation, OrgStatus, Role,
    SessionToken, User, utcnow,
)
from .security import hash_password, hash_token, issue_token, needs_rehash, verify_password


def slugify(name: str, db: Session) -> str:
    """A URL-safe, unique slug. Collisions get a numeric suffix rather
    than failing signup — two providers may legitimately share a name."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60] or "org"

    existing = set(
        db.execute(
            select(Organisation.slug).where(Organisation.slug.like(f"{base}%"))
        ).scalars()
    )
    if base not in existing:
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"
        if candidate not in existing:
            return candidate
    return f"{base}-{int(datetime.now(timezone.utc).timestamp())}"


def audit(db: Session, *, action: str, organisation_id=None, actor_user_id=None,
          target=None, source_ip=None) -> None:
    db.add(AuditEvent(
        organisation_id=organisation_id, actor_user_id=actor_user_id,
        action=action, target=target, source_ip=source_ip,
    ))


def register_organisation(db: Session, *, email: str, password: str, name: str,
                          rto_code: str | None, settings, source_ip=None) -> str | None:
    """Create a user, an organisation and an owner membership atomically.

    Returns a verification token, or None when the email is already
    registered. The caller must respond identically either way: a
    different response for a known address turns signup into an account
    enumeration oracle.
    """
    email = email.lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        return None

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()

    organisation = Organisation(
        name=name.strip(), slug=slugify(name, db), contact_email=email, rto_code=rto_code,
        status=OrgStatus.PENDING_VERIFICATION,
    )
    db.add(organisation)
    db.flush()

    db.add(Membership(user_id=user.id, organisation_id=organisation.id, role=Role.OWNER))

    plaintext, digest = issue_token()
    db.add(EmailVerification(
        token_hash=digest, user_id=user.id,
        expires_at=utcnow() + timedelta(hours=settings.verification_ttl_hours),
    ))

    audit(db, action="organisation.created", organisation_id=organisation.id,
          actor_user_id=user.id, target=organisation.slug, source_ip=source_ip)
    db.commit()
    return plaintext


def consume_verification(db: Session, token: str, source_ip=None) -> bool:
    """Single-use. Activates every organisation the user owns."""
    row = db.execute(
        select(EmailVerification).where(EmailVerification.token_hash == hash_token(token))
    ).scalar_one_or_none()

    if row is None or row.consumed_at is not None:
        return False

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return False

    row.consumed_at = utcnow()
    user = row.user
    user.email_verified_at = utcnow()

    owned = db.execute(
        select(Organisation)
        .join(Membership, Membership.organisation_id == Organisation.id)
        .where(Membership.user_id == user.id, Membership.role == Role.OWNER)
    ).scalars().all()
    for organisation in owned:
        if organisation.status == OrgStatus.PENDING_VERIFICATION:
            organisation.status = OrgStatus.ACTIVE
            audit(db, action="organisation.activated", organisation_id=organisation.id,
                  actor_user_id=user.id, source_ip=source_ip)

    audit(db, action="email.verified", actor_user_id=user.id, source_ip=source_ip)
    db.commit()
    return True


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    """Verify credentials. Runs the hash comparison even when the user
    does not exist, so response timing does not reveal which addresses
    are registered. Upgrades a stale hash on success."""
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()

    if user is None:
        # Dummy verification against a real hash of a random value:
        # same work, no account.
        verify_password(password, hash_password("timing-equalisation-placeholder"))
        return None

    if not verify_password(password, user.password_hash):
        return None

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()

    return user


def start_session(db: Session, user: User, settings, source_ip=None) -> tuple[str, datetime]:
    plaintext, digest = issue_token()
    expires_at = utcnow() + timedelta(hours=settings.session_ttl_hours)
    db.add(SessionToken(token_hash=digest, user_id=user.id, expires_at=expires_at))
    audit(db, action="session.started", actor_user_id=user.id, source_ip=source_ip)
    db.commit()
    return plaintext, expires_at


def end_session(db: Session, token: str) -> None:
    row = db.execute(
        select(SessionToken).where(SessionToken.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
        audit(db, action="session.ended", actor_user_id=row.user_id)
        db.commit()


def organisations_for(db: Session, user: User) -> list[tuple[Organisation, Role]]:
    rows = db.execute(
        select(Organisation, Membership.role)
        .join(Membership, Membership.organisation_id == Organisation.id)
        .where(Membership.user_id == user.id)
        .order_by(Organisation.id)
    ).all()
    return [(org, role) for org, role in rows]


def owner_count(db: Session, organisation_id: int) -> int:
    return db.execute(
        select(func.count(Membership.id)).where(
            Membership.organisation_id == organisation_id, Membership.role == Role.OWNER
        )
    ).scalar_one()
