"""Self-serve signup, verification and sessions."""

from conftest import register


def test_signup_creates_an_organisation_the_owner_can_see(client, email):
    headers, org_id = register(client, email, email="head@tafe.edu.au", org="Riverside TAFE")
    body = client.get("/auth/me", headers=headers).json()
    assert body["email_verified"] is True
    org = body["organisations"][0]
    assert org["name"] == "Riverside TAFE"
    assert org["role"] == "owner"
    assert org["status"] == "active"
    assert org["id"] == org_id


def test_organisation_is_inactive_until_email_is_verified(client, email):
    client.post("/auth/signup", json={
        "email": "new@rto.edu.au", "password": "a-long-enough-password",
        "organisation_name": "New RTO",
    })
    r = client.post("/auth/signin", json={
        "email": "new@rto.edu.au", "password": "a-long-enough-password"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    body = client.get("/auth/me", headers=headers).json()
    assert body["email_verified"] is False
    org_id = body["organisations"][0]["id"]
    assert body["organisations"][0]["status"] == "pending_verification"

    # Can look around, cannot act outwards.
    assert client.get(f"/orgs/{org_id}", headers=headers).status_code == 200
    assert client.post(f"/orgs/{org_id}/candidates", headers=headers).status_code == 403


def test_signup_does_not_reveal_whether_an_address_is_registered(client, email):
    first = client.post("/auth/signup", json={
        "email": "dup@rto.edu.au", "password": "a-long-enough-password",
        "organisation_name": "First"})
    second = client.post("/auth/signup", json={
        "email": "dup@rto.edu.au", "password": "another-long-password",
        "organisation_name": "Second"})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    # Only the genuine signup produced a verification email.
    assert len([a for a, _ in email.sent if a == "dup@rto.edu.au"]) == 1


def test_wrong_password_and_unknown_user_are_indistinguishable(client, email):
    register(client, email, email="real@rto.edu.au", org="Real RTO")
    wrong = client.post("/auth/signin", json={
        "email": "real@rto.edu.au", "password": "not-the-right-password"})
    unknown = client.post("/auth/signin", json={
        "email": "ghost@rto.edu.au", "password": "not-the-right-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_verification_token_is_single_use(client, email):
    client.post("/auth/signup", json={
        "email": "once@rto.edu.au", "password": "a-long-enough-password",
        "organisation_name": "Once"})
    token = email.sent[-1][1]
    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    assert client.post("/auth/verify", json={"token": token}).status_code == 400


def test_signout_revokes_the_session_immediately(client, email):
    headers, _ = register(client, email, email="out@rto.edu.au", org="Out RTO")
    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.post("/auth/signout", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_unauthenticated_and_garbage_tokens_are_rejected(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_disposable_email_domains_are_rejected(client):
    r = client.post("/auth/signup", json={
        "email": "burner@mailinator.com", "password": "a-long-enough-password",
        "organisation_name": "Burner"})
    assert r.status_code == 422


def test_short_passwords_are_rejected(client):
    r = client.post("/auth/signup", json={
        "email": "weak@rto.edu.au", "password": "short", "organisation_name": "Weak"})
    assert r.status_code == 422


def test_duplicate_organisation_names_get_distinct_slugs(client, email):
    register(client, email, email="a@one.edu.au", org="Melbourne Training")
    h2, _ = register(client, email, email="b@two.edu.au", org="Melbourne Training")
    slugs = {o["slug"] for o in client.get("/auth/me", headers=h2).json()["organisations"]}
    assert slugs == {"melbourne-training-2"}
