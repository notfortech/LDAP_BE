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
    ("GET", "/orgs/{organisation_id}/constructs"),
    ("GET", "/orgs/{organisation_id}/candidates"),
    ("POST", "/orgs/{organisation_id}/candidates"),
    ("GET", "/orgs/{organisation_id}/candidates/{candidate_id}"),
    ("PUT", "/orgs/{organisation_id}/candidates/{candidate_id}/assignments"),
    ("GET", "/orgs/{organisation_id}/candidates/{candidate_id}/pathway"),
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

    def add_candidate(headers, org_id, address):
        r = client.post(f"/orgs/{org_id}/candidates", headers=headers,
                        json={"email": address})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {
        "alice": alice, "alice_org": alice_org,
        "alice_candidate": add_candidate(alice, alice_org, "learner@north.edu.au"),
        "bob": bob, "bob_org": bob_org,
        "bob_candidate": add_candidate(bob, bob_org, "learner@south.edu.au"),
    }


# A minimal valid body per route, so a 422 never masks a missing 404.
BODIES = {
    ("PUT", "/orgs/{organisation_id}/candidates/{candidate_id}/assignments"):
        {"construct_ids": ["SK_ETHICS"]},
    ("POST", "/orgs/{organisation_id}/candidates"): {"email": "new@example.edu.au"},
}


def _fill(template, org_id, candidate_id):
    return template.format(organisation_id=org_id, candidate_id=candidate_id)


@pytest.mark.parametrize("method,template", ORG_SCOPED)
def test_other_tenants_organisation_is_not_reachable(client, two_tenants, method, template):
    """Alice names Bob's organisation and Bob's candidate. Both must 404."""
    path = _fill(template, two_tenants["bob_org"], two_tenants["bob_candidate"])
    response = client.request(method, path, headers=two_tenants["alice"],
                              json=BODIES.get((method, template)))
    assert response.status_code == 404, (
        f"{method} {path} returned {response.status_code} to a non-member. "
        "Cross-tenant access is a release-blocking defect."
    )


@pytest.mark.parametrize("method,template", [
    (m, t) for m, t in ORG_SCOPED if "{candidate_id}" in t
])
def test_other_tenants_candidate_is_not_reachable_via_own_org(client, two_tenants, method, template):
    """The subtler attack: Alice uses her OWN organisation id, which she
    is entitled to, and Bob's candidate id. The candidate lookup must be
    filtered by organisation, not merely checked after the fact."""
    path = _fill(template, two_tenants["alice_org"], two_tenants["bob_candidate"])
    response = client.request(method, path, headers=two_tenants["alice"],
                              json=BODIES.get((method, template)))
    assert response.status_code == 404, (
        f"{method} {path} leaked another tenant's candidate through the "
        "caller's own organisation."
    )


@pytest.mark.parametrize("method,template", ORG_SCOPED)
def test_own_organisation_is_reachable(client, two_tenants, method, template):
    """The negative tests above would also pass if every route were
    broken, so prove the same calls work for the rightful member."""
    body = BODIES.get((method, template))
    if (method, template) == ("POST", "/orgs/{organisation_id}/candidates"):
        body = {"email": "second@north.edu.au"}
    path = _fill(template, two_tenants["alice_org"], two_tenants["alice_candidate"])
    response = client.request(method, path, headers=two_tenants["alice"], json=body)
    # 409 on the pathway route means "no formal attempt yet", which is a
    # correct authorised answer -- the point here is that access is not
    # refused.
    assert response.status_code in (200, 201, 409), response.text


@pytest.mark.parametrize("method,template", ORG_SCOPED)
def test_unauthenticated_access_is_rejected(client, two_tenants, method, template):
    path = _fill(template, two_tenants["alice_org"], two_tenants["alice_candidate"])
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
