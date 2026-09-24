"""
Unit tests for data_model.py — the Python-side twin of /js/core/state.js.

Covers: factory shape/defaults, id generation, JSON round-trip, and the
shallow structural validator (project rule: OCR/data is never automatically
considered "verified" — this validator is the API-boundary sanity check
that everything downstream, including the document-generation engines,
implicitly relies on getting a well-shaped Application).
"""

import data_model


def test_generate_id_has_prefix_and_is_unique():
    ids = {data_model.generate_id("APP") for _ in range(50)}
    assert len(ids) == 50, "generate_id produced a collision across 50 calls"
    assert all(i.startswith("APP_") for i in ids)


def test_empty_passport_shape():
    passport = data_model.empty_passport()
    assert passport["current"]["number"] == ""
    assert passport["current"]["mrzValid"] is None, "mrzValid must default to None (not-checked), never True/False"
    assert passport["old"] is None
    assert passport["verificationStatus"] == "Not Started"


def test_empty_person_embeds_a_fresh_passport_each_time():
    p1 = data_model.empty_person()
    p2 = data_model.empty_person()
    p1["passport"]["current"]["number"] = "X1"
    assert p2["passport"]["current"]["number"] == "", "empty_person() must not share a mutable passport dict across calls"


def test_create_empty_application_has_all_required_top_level_keys():
    app = data_model.create_empty_application(created_by="customercare@khannatravels.com")
    for key in data_model.REQUIRED_TOP_LEVEL_KEYS:
        assert key in app, f"create_empty_application() is missing required key {key!r}"
    assert app["status"] == "Draft"
    assert app["createdBy"] == "customercare@khannatravels.com"
    assert app["activity"][0]["type"] == "created"
    assert app["id"].startswith("APP_")


def test_create_empty_application_ids_are_unique_across_calls():
    a1 = data_model.create_empty_application()
    a2 = data_model.create_empty_application()
    assert a1["id"] != a2["id"]


def test_json_round_trip_is_lossless():
    app = data_model.create_empty_application(created_by="qa@khannatravels.com")
    raw = data_model.to_json(app)
    round_tripped = data_model.from_json(raw)
    assert round_tripped == app


def test_validate_application_accepts_a_freshly_created_application():
    app = data_model.create_empty_application()
    assert data_model.validate_application(app) == []


def test_validate_application_rejects_non_dict_payload():
    errors = data_model.validate_application("not a dict")
    assert errors and "JSON object" in errors[0]


def test_validate_application_flags_every_missing_required_key():
    errors = data_model.validate_application({"id": "APP_x"})
    missing = {e.split(": ")[1] for e in errors if e.startswith("Missing required field")}
    expected = set(data_model.REQUIRED_TOP_LEVEL_KEYS) - {"id"}
    assert missing == expected


def test_validate_application_flags_unknown_status():
    app = data_model.create_empty_application()
    app["status"] = "Definitely Not A Real Status"
    errors = data_model.validate_application(app)
    assert any("Unknown status" in e for e in errors)


def test_validate_application_flags_wrong_typed_lists():
    app = data_model.create_empty_application()
    app["travellers"] = "should be a list"
    app["documents"] = {"also": "wrong"}
    errors = data_model.validate_application(app)
    assert any("'travellers' must be a list" in e for e in errors)
    assert any("'documents' must be a list" in e for e in errors)


def test_every_canonical_status_is_accepted():
    app = data_model.create_empty_application()
    for status in data_model.STATUSES:
        app["status"] = status
        assert data_model.validate_application(app) == [], f"status {status!r} should be valid"
