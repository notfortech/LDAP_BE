"""Cross-tenant isolation. A release gate.

Two organisations are created, then every organisation-scoped endpoint
is called by the wrong tenant. Any response that is not 404 fails the
build.

The meta-test at the bottom matters more than the individual cases:
without it, coverage silently rots as endpoints are added, and a suite
that passes because it tests nothing is worse than no suite at all.
"""

import pytest
from conftest import register

# Every organisation-scoped route, as (method, path template). A route
# present in the application but missing here fails test_every_org_scoped
# _route_is_covered below, which is the point.
ORG_SCOPED = [
    ("GET", "/orgs/{organisation_id}"),
    ("GET", "/orgs/{organisation_id}/candidates"),
    ("POST", "/orgs/{organisation_id}/candidates"),
]


def _org_scoped_routes(app):
    """Every organisation-scoped (method, path) the application exposes.

    Read from the generated OpenAPI schema rather than by walking
    app.routes. Included routers are not always flattened into the
    parent's route list -- some FastAPI versions keep them in an opaque
    wrapper with no public way in -- so a route walk silently finds
    nothing and the coverage check below passes while testing zero
    endpoints. app.openapi() is public, stable across versions, and
    works even when the schema is not served (as in production).
    """
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        if "{organisation_id}" in path
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


@pytest.fixture
def two_tenants(client, email):
    alice, alice_org = register(client, email, email="alice@north.edu.au", org="North TAFE")
    bob, bob_org = register(client, email, email="bob@south.edu.au", org="South TAFE")
    assert alice_org != bob_org
    return {"alice": alice, "alice_org": alice_org, "bob": bob, "bob_org": bob_org}


@pytest.mark.parametrize("method,template", ORG_SCOPED)
def test_other_tenants_organisation_is_not_reachable(client, two_tenants, method, template):
    path = template.format(organisation_id=two_tenants["bob_org"])
    response = client.request(method, path, headers=two_tenants["alice"])
    assert response.status_code == 404, (
        f"{method} {path} returned {response.status_code} to a non-member. "
        "Cross-tenant access is a release-blocking defect."
    )


@pytest.mark.parametrize("method,template", ORG_SCOPED)
def test_own_organisation_is_reachable(client, two_tenants, method, template):
    """The negative tests above would also pass if every route were
    broken, so prove the same calls work for the rightful member."""
    path = template.format(organisation_id=two_tenants["alice_org"])
    response = client.request(method, path, headers=two_tenants["alice"])
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("method,template", ORG_SCOPED)
def test_unauthenticated_access_is_rejected(client, two_tenants, method, template):
    path = template.format(organisation_id=two_tenants["alice_org"])
    assert client.request(method, path).status_code == 401


def test_nonexistent_organisation_is_indistinguishable_from_someone_elses(client, two_tenants):
    """Both must be 404. If a foreign organisation returned 403 and an
    absent one 404, an outsider could enumerate the tenant list by
    walking ids."""
    foreign = client.get(f"/orgs/{two_tenants['bob_org']}", headers=two_tenants["alice"])
    absent = client.get("/orgs/999999", headers=two_tenants["alice"])
    assert foreign.status_code == absent.status_code == 404
    assert foreign.json() == absent.json()


def test_every_org_scoped_route_is_covered(client):
    """Fails when an organisation-scoped route exists that this suite
    does not exercise. Add the route to ORG_SCOPED -- do not delete this
    test."""
    declared = {(m, p) for m, p in ORG_SCOPED}
    actual = _org_scoped_routes(client.app)
    assert actual, (
        "Route discovery found nothing, so this suite would pass vacuously. "
        "Fix the walk before trusting any result from it."
    )

    missing = actual - declared
    assert not missing, (
        f"Organisation-scoped routes not covered by the cross-tenant suite: "
        f"{sorted(missing)}. Add them to ORG_SCOPED."
    )

    stale = declared - actual
    assert not stale, f"ORG_SCOPED lists routes that no longer exist: {sorted(stale)}"
