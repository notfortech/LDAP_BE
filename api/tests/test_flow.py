"""The assessment-to-pathway flow, end to end.

Invite a candidate, take the assessment, score it deterministically,
read the passport, generate a pathway.
"""

import pytest
from aptus_api.models import TrainingReference
from conftest import register


@pytest.fixture
def org(client, email):
    headers, org_id = register(client, email, email="admin@riverside.edu.au",
                               org="Riverside TAFE")
    return {"headers": headers, "id": org_id}


def invite(client, org, address="learner@riverside.edu.au"):
    r = client.post(f"/orgs/{org['id']}/candidates", headers=org["headers"],
                    json={"email": address, "display_name": "A Learner"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], {"Authorization": f"Bearer {body['access_token']}"}


def take(client, cand_headers, set_id="full", option="A"):
    items = client.get(f"/assessment/{set_id}", headers=cand_headers).json()["items"]
    return client.post(f"/assessment/{set_id}/submit", headers=cand_headers,
                       json={"responses": {i["item_id"]: option for i in items}})


def test_full_flow_invite_assess_score_passport_pathway(client, org, db_session=None):
    candidate_id, cand = invite(client, org)

    # The candidate sees the full 24-item set.
    assessment = client.get("/assessment/full", headers=cand).json()
    assert len(assessment["items"]) == 24
    assert assessment["counts_toward_passport"] is True
    assert assessment["time_limit_minutes"] == 40

    result = take(client, cand).json()
    assert result["overall"]["band"] == "Strong"
    assert result["overall"]["normalised"] == 1.0
    assert len(result["constructs"]) == 12
    # Every result names the engine configuration that produced it.
    assert result["engine_config_version"] == "1.0.0"

    detail = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}",
                        headers=org["headers"]).json()
    assert detail["formal_attempts"] == 1
    assert detail["passport"]["attempt_count"] == 1
    assert len(detail["passport"]["attempts"][0]["constructs"]) == 12
    assert detail["passport"]["attempts"][0]["engine_config_digest"]


def test_practice_does_not_reach_the_passport(client, org):
    candidate_id, cand = invite(client, org)
    assert take(client, cand, set_id="quick").json()["counts_toward_passport"] is False

    detail = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}",
                        headers=org["headers"]).json()
    assert detail["formal_attempts"] == 0
    assert detail["passport"]["attempt_count"] == 0

    # And no pathway, because a pathway must come from the assessment
    # that counts.
    r = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}/pathway",
                   headers=org["headers"])
    assert r.status_code == 409


def test_assignments_narrow_the_assessment(client, org):
    candidate_id, cand = invite(client, org)
    r = client.put(f"/orgs/{org['id']}/candidates/{candidate_id}/assignments",
                   headers=org["headers"],
                   json={"construct_ids": ["SK_ETHICS", "SK_NUMERACY"]})
    assert r.status_code == 200

    items = client.get("/assessment/full", headers=cand).json()["items"]
    assert 0 < len(items) < 24

    scored = take(client, cand).json()["constructs"]
    assert {c["construct_id"] for c in scored} == {"SK_ETHICS", "SK_NUMERACY"}


def test_responses_for_unassigned_items_are_discarded(client, org):
    """A candidate assigned two constructs cannot be scored on twelve by
    submitting answers they were never shown."""
    candidate_id, cand = invite(client, org)
    client.put(f"/orgs/{org['id']}/candidates/{candidate_id}/assignments",
               headers=org["headers"], json={"construct_ids": ["SK_ETHICS"]})

    every_item = {i["question_id"]: "A" for i in
                  __import__("json").loads(
                      (__import__("pathlib").Path(client.app.state.settings.database_url) and
                       None) or "{}") } if False else None

    # Submit answers to the whole bank regardless of assignment.
    from aptus_api.engine_bridge import get_item_bank
    everything = {qid: "A" for qid in get_item_bank().item_ids()}
    scored = client.post("/assessment/full/submit", headers=cand,
                         json={"responses": everything}).json()["constructs"]
    assert {c["construct_id"] for c in scored} == {"SK_ETHICS"}


def test_unknown_construct_in_assignment_is_rejected(client, org):
    candidate_id, _ = invite(client, org)
    r = client.put(f"/orgs/{org['id']}/candidates/{candidate_id}/assignments",
                   headers=org["headers"], json={"construct_ids": ["SK_NOT_REAL"]})
    assert r.status_code == 422
    assert "SK_NOT_REAL" in r.text


def test_invalid_option_is_rejected_not_scored(client, org):
    _, cand = invite(client, org)
    items = client.get("/assessment/full", headers=cand).json()["items"]
    responses = {i["item_id"]: "A" for i in items}
    responses[items[0]["item_id"]] = "Z"
    r = client.post("/assessment/full/submit", headers=cand, json={"responses": responses})
    assert r.status_code == 422


def test_seat_cap_blocks_the_third_candidate(client, org):
    """Free tier is two seats."""
    invite(client, org, "one@riverside.edu.au")
    invite(client, org, "two@riverside.edu.au")
    r = client.post(f"/orgs/{org['id']}/candidates", headers=org["headers"],
                    json={"email": "three@riverside.edu.au"})
    assert r.status_code == 402
    assert "2 candidates" in r.json()["detail"]


def test_duplicate_invitation_is_rejected(client, org):
    invite(client, org, "dup@riverside.edu.au")
    r = client.post(f"/orgs/{org['id']}/candidates", headers=org["headers"],
                    json={"email": "dup@riverside.edu.au"})
    assert r.status_code == 409


def test_candidate_token_reaches_only_its_own_assessment(client, org, email):
    """A candidate token is not an organisation credential."""
    _, cand = invite(client, org)
    assert client.get(f"/orgs/{org['id']}/candidates", headers=cand).status_code == 401
    assert client.get("/auth/me", headers=cand).status_code == 401


def test_scoring_through_the_api_is_reproducible(client, org):
    """Two candidates, identical answers, identical scores and digest."""
    _, a = invite(client, org, "a@riverside.edu.au")
    _, b = invite(client, org, "b@riverside.edu.au")
    ra, rb = take(client, a, option="C").json(), take(client, b, option="C").json()
    assert ra["overall"] == rb["overall"]
    assert ra["constructs"] == rb["constructs"]


class TestPathway:
    def _seed_reference(self, client, org, construct_id, unit_code, *,
                        organisation_id=None, lineage=None, forked_from=None,
                        verified=False):
        from aptus_api import db as db_module
        session = db_module._SessionLocal()
        try:
            ref = TrainingReference(
                lineage_id=lineage or f"lin-{unit_code}", version=1, is_current=True,
                forked_from_lineage_id=forked_from, organisation_id=organisation_id,
                construct_id=construct_id, unit_code=unit_code,
                unit_title=f"Unit {unit_code}",
                qualification_title="BSB40120 Certificate IV in Business",
                career_path="Administration Officer",
                training_gov_url=f"https://training.gov.au/Training/Details/{unit_code}",
                verified=verified,
            )
            session.add(ref)
            session.commit()
        finally:
            session.close()

    def test_pathway_names_real_units_for_strongest_constructs(self, client, org):
        candidate_id, cand = invite(client, org)
        self._seed_reference(client, org, "SK_ETHICS", "BSBPEF401", verified=True)
        take(client, cand)

        pathway = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}/pathway",
                             headers=org["headers"]).json()
        assert len(pathway["strongest_constructs"]) == 3
        assert pathway["generated_from"]["engine_config_version"] == "1.0.0"

        found = [s for s in pathway["strongest_constructs"]
                 if s["construct_id"] == "SK_ETHICS"]
        if found:
            ref = found[0]["references"][0]
            assert ref["unit_code"] == "BSBPEF401"
            assert ref["training_gov_url"].startswith("https://training.gov.au/")
            assert ref["source"] == "global"

    def test_organisation_fork_replaces_the_global_it_diverged_from(self, client, org):
        candidate_id, cand = invite(client, org)
        self._seed_reference(client, org, "SK_ETHICS", "GLOBAL01", lineage="lin-ethics")
        self._seed_reference(client, org, "SK_ETHICS", "LOCAL01",
                             organisation_id=org["id"], lineage="lin-ethics-fork",
                             forked_from="lin-ethics")
        client.put(f"/orgs/{org['id']}/candidates/{candidate_id}/assignments",
                   headers=org["headers"], json={"construct_ids": ["SK_ETHICS"]})
        take(client, cand)

        pathway = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}/pathway",
                             headers=org["headers"]).json()
        section = pathway["strongest_constructs"][0]
        codes = [r["unit_code"] for r in section["references"]]
        assert codes == ["LOCAL01"], (
            "The forked entry must replace the global default, not sit beside it."
        )
        assert section["references"][0]["source"] == "organisation"

    def test_an_unforked_global_is_returned(self, client, org):
        """Guards the test above from passing because nothing was found:
        without a fork, the global entry must come back."""
        candidate_id, cand = invite(client, org)
        self._seed_reference(client, org, "SK_ETHICS", "GLOBALONLY", lineage="lin-g")
        client.put(f"/orgs/{org['id']}/candidates/{candidate_id}/assignments",
                   headers=org["headers"], json={"construct_ids": ["SK_ETHICS"]})
        take(client, cand)
        pathway = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}/pathway",
                             headers=org["headers"]).json()
        section = pathway["strongest_constructs"][0]
        assert [r["unit_code"] for r in section["references"]] == ["GLOBALONLY"]
        assert section["references"][0]["source"] == "global"

    def test_unverified_mappings_are_counted_not_hidden(self, client, org):
        candidate_id, cand = invite(client, org)
        self._seed_reference(client, org, "SK_ETHICS", "UNVER01", verified=False)
        client.put(f"/orgs/{org['id']}/candidates/{candidate_id}/assignments",
                   headers=org["headers"], json={"construct_ids": ["SK_ETHICS"]})
        take(client, cand)

        pathway = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}/pathway",
                             headers=org["headers"]).json()
        assert pathway["unverified_reference_count"] == 1
        assert pathway["strongest_constructs"][0]["references"][0]["verified"] is False

    def test_constructs_without_references_are_reported_as_gaps(self, client, org):
        candidate_id, cand = invite(client, org)
        take(client, cand)
        pathway = client.get(f"/orgs/{org['id']}/candidates/{candidate_id}/pathway",
                             headers=org["headers"]).json()
        assert len(pathway["constructs_without_references"]) == 3
