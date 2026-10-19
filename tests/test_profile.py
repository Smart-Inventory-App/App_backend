"""Endpoints de perfil: valores por defecto, edición y el token de notificaciones."""
from uuid import UUID

import pytest

from app.models.user import AuthUser
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def test_get_profile_uses_defaults_when_no_profile_exists_yet(client, db):
    resp = client.get("/profile/", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["sub"] == TEST_USER_ID
    assert body["coverageDaysThreshold"] == 7
    assert body["expiryDaysThreshold"] == 7
    assert body["alertCheckHour"] == 8
    assert body["userType"] == "individuo"


def test_update_profile_persists_every_field(client, db):
    payload = {
        "firstName": "Ana",
        "lastName": "Gomez",
        "username": "anag",
        "coverageDaysThreshold": 10,
        "expiryDaysThreshold": 3,
        "alertCheckHour": 14,
        "userType": "comercio",
    }

    resp = client.put("/profile/", json=payload, headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["firstName"] == "Ana"
    assert body["lastName"] == "Gomez"
    assert body["username"] == "anag"
    assert body["coverageDaysThreshold"] == 10
    assert body["expiryDaysThreshold"] == 3
    assert body["alertCheckHour"] == 14
    assert body["userType"] == "comercio"


def test_update_profile_without_optional_fields_keeps_the_defaults(client, db):
    resp = client.put("/profile/", json={"firstName": "Solo", "lastName": "Nombre"}, headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["coverageDaysThreshold"] == 7
    assert body["alertCheckHour"] == 8
    assert body["userType"] == "individuo"


def test_register_notification_token_saves_it_on_the_auth_user(client, db):
    resp = client.post("/profile/register_notification_token", json={"token": "fcm-abc"}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["message"] == "Token registered successfully"
    user = db.query(AuthUser).filter(AuthUser.id == UUID(TEST_USER_ID)).first()
    assert user.firebase_token == "fcm-abc"


def test_register_notification_token_when_the_caller_has_no_auth_users_row(client, db, monkeypatch):
    from app.core.security import get_current_user
    from app.main import app

    ghost = {"sub": "not-a-uuid", "email": "x@test.com"}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: ghost)

    resp = client.post("/profile/register_notification_token", json={"token": "t"}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["message"] == "User not found"


def test_unregister_notification_token_clears_it(client, db):
    client.post("/profile/register_notification_token", json={"token": "fcm-xyz"}, headers=AUTH)

    resp = client.delete("/profile/unregister_notification_token", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["message"] == "Token unregistered successfully"
    user = db.query(AuthUser).filter(AuthUser.id == UUID(TEST_USER_ID)).first()
    assert user.firebase_token is None


def test_unregister_notification_token_when_the_caller_has_no_auth_users_row(client, db, monkeypatch):
    from app.core.security import get_current_user
    from app.main import app

    ghost = {"sub": "not-a-uuid", "email": "x@test.com"}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: ghost)

    resp = client.delete("/profile/unregister_notification_token", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["message"] == "User not found"


# ── límites del perfil ────────────────────────────────────────────────────────

def put_profile(client, **fields):
    payload = {"firstName": "Ana", "lastName": "Gomez", **fields}
    return client.put("/profile/", json=payload, headers=AUTH)


def test_the_name_the_last_name_and_the_username_accept_exactly_20_characters(client, db):
    resp = put_profile(client, firstName="a" * 20, lastName="b" * 20, username="c" * 20)

    assert resp.status_code == 200
    body = resp.json()
    assert (body["firstName"], body["lastName"], body["username"]) == ("a" * 20, "b" * 20, "c" * 20)


def test_a_name_longer_than_20_characters_is_rejected(client, db):
    assert put_profile(client, firstName="a" * 21).status_code == 422


def test_a_last_name_longer_than_20_characters_is_rejected(client, db):
    assert put_profile(client, lastName="b" * 21).status_code == 422


def test_a_username_longer_than_20_characters_is_rejected(client, db):
    assert put_profile(client, username="c" * 21).status_code == 422


def test_a_rejected_profile_keeps_what_was_saved_before(client, db):
    put_profile(client, firstName="Ana", username="anag")

    put_profile(client, firstName="x" * 30, username="y" * 30)

    body = client.get("/profile/", headers=AUTH).json()
    assert (body["firstName"], body["username"]) == ("Ana", "anag")


@pytest.mark.parametrize("field", ["coverageDaysThreshold", "expiryDaysThreshold"])
@pytest.mark.parametrize("days", [2, 7, 30, 90])
def test_the_alert_days_accept_the_whole_range_from_2_to_90(client, db, field, days):
    resp = put_profile(client, **{field: days})

    assert resp.status_code == 200
    assert resp.json()[field] == days


@pytest.mark.parametrize("field", ["coverageDaysThreshold", "expiryDaysThreshold"])
@pytest.mark.parametrize("days", [-1, 0, 1, 91, 365])
def test_the_alert_days_outside_the_range_are_rejected(client, db, field, days):
    assert put_profile(client, **{field: days}).status_code == 422


def test_the_alert_check_hour_still_goes_from_0_to_23(client, db):
    assert put_profile(client, alertCheckHour=0).json()["alertCheckHour"] == 0
    assert put_profile(client, alertCheckHour=23).json()["alertCheckHour"] == 23
    assert put_profile(client, alertCheckHour=24).status_code == 422
    assert put_profile(client, alertCheckHour=-1).status_code == 422
