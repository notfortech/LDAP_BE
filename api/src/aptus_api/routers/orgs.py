"""Organisation-scoped endpoints.

Every route carries {organisation_id} in the path and resolves it
through org_context, which checks membership. The path selects among
the caller's own organisations; it never grants access to one.
"""

from fastapi import APIRouter, Depends

from ..deps import OrgContext, org_context, require_operating_org

router = APIRouter(prefix="/orgs/{organisation_id}", tags=["organisations"])


@router.get("")
def get_organisation(ctx: OrgContext = Depends(org_context)):
    org = ctx.organisation
    return {
        "id": org.id, "name": org.name, "slug": org.slug,
        "status": org.status.value, "rto_code": org.rto_code,
        "your_role": ctx.role.value, "can_operate": org.can_operate,
    }


@router.get("/candidates")
def list_candidates(ctx: OrgContext = Depends(org_context)):
    """Placeholder for the ported candidate roster. Present now so the
    cross-tenant suite covers an organisation-scoped read path from the
    first commit rather than after the data lands."""
    return {"organisation_id": ctx.organisation.id, "candidates": []}


@router.post("/candidates")
def invite_candidate(ctx: OrgContext = Depends(require_operating_org)):
    """Placeholder for candidate invitation. Guarded by
    require_operating_org: an unverified organisation cannot cause email
    to be sent in its name."""
    return {"organisation_id": ctx.organisation.id, "status": "not_implemented"}
