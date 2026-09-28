from fastapi.testclient import TestClient

from app.config import Settings, get_settings


def test_password_minimum_is_eight_characters_for_setup_and_invitation(client):
    short = client.post("/api/setup/admin", json={"email": "owner@example.test", "password": "Test-12"})
    assert short.status_code == 422
    assert short.json()["detail"] == "密码至少需要 8 个字符"
    assert client.get("/api/setup/status").json() == {"required": True}
    created = client.post("/api/setup/admin", json={"email": "owner@example.test", "password": "Test-123"})
    assert created.status_code == 201
    invitation = client.post("/api/admin/invitations", json={"email": "member@example.test", "expires_in_hours": 24}).json()
    client.post("/api/auth/logout")
    short = client.post("/api/auth/register/invitation", json={"token": invitation["token"], "password": "Test-12"})
    assert short.status_code == 422
    registered = client.post("/api/auth/register/invitation", json={"token": invitation["token"], "password": "Test-123"})
    assert registered.status_code == 201
    client.post("/api/auth/logout")
    for email in ["owner@example.test", "member@example.test"]:
        assert client.post("/api/auth/login", json={"email": email, "password": "Test-123"}).status_code == 200
        client.post("/api/auth/logout")


def test_setup_then_invite_only_registration(client):
    assert client.get("/api/setup/status").json() == {"required": True}

    admin = client.post(
        "/api/setup/admin",
        json={"email": "admin@example.test", "password": "Correct-Horse-42"},
    )
    assert admin.status_code == 201
    assert admin.json()["role"] == "admin"
    assert client.get("/api/setup/status").json() == {"required": False}

    duplicate_setup = client.post(
        "/api/setup/admin",
        json={"email": "other@example.test", "password": "Correct-Horse-42"},
    )
    assert duplicate_setup.status_code == 409

    invitation = client.post(
        "/api/admin/invitations",
        json={"email": "user@example.test", "expires_in_hours": 24},
    )
    assert invitation.status_code == 201
    token = invitation.json()["token"]

    registered = client.post(
        "/api/auth/register/invitation",
        json={"token": token, "password": "Correct-Horse-43"},
    )
    assert registered.status_code == 201
    assert registered.json()["role"] == "user"

    reused = client.post(
        "/api/auth/register/invitation",
        json={"token": token, "password": "Correct-Horse-44"},
    )
    assert reused.status_code == 409


def test_login_uses_http_only_cookie_and_logout_revokes_it(client):
    client.post(
        "/api/setup/admin",
        json={"email": "admin@example.test", "password": "Correct-Horse-42"},
    )
    client.post("/api/auth/logout")

    login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "Correct-Horse-42"},
    )
    assert login.status_code == 200
    assert "HttpOnly" in login.headers["set-cookie"]
    assert client.get("/api/auth/me").json()["email"] == "admin@example.test"

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_non_admin_cannot_create_invitation(client):
    client.post(
        "/api/setup/admin",
        json={"email": "admin@example.test", "password": "Correct-Horse-42"},
    )
    invitation = client.post(
        "/api/admin/invitations",
        json={"email": "user@example.test", "expires_in_hours": 24},
    ).json()
    client.post(
        "/api/auth/register/invitation",
        json={"token": invitation["token"], "password": "Correct-Horse-43"},
    )

    assert client.post(
        "/api/admin/invitations",
        json={"email": "another@example.test", "expires_in_hours": 24},
    ).status_code == 403


def test_admin_can_list_and_disable_invited_user(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as admin:
        admin_user = admin.post(
            "/api/setup/admin",
            json={"email": "admin@example.test", "password": "Correct-Horse-42"},
        ).json()
        invitation = admin.post(
            "/api/admin/invitations",
            json={"email": "member@example.test", "expires_in_hours": 24},
        ).json()
        with TestClient(app) as member:
            member_user = member.post(
                "/api/auth/register/invitation",
                json={"token": invitation["token"], "password": "Correct-Horse-43"},
            ).json()
            users = admin.get("/api/admin/users")
            assert users.status_code == 200
            assert {item["email"] for item in users.json()["items"]} == {"admin@example.test", "member@example.test"}
            disabled = admin.patch(f"/api/admin/users/{member_user['id']}", json={"is_active": False})
            assert disabled.status_code == 200
            assert disabled.json()["is_active"] is False
            assert member.get("/api/auth/me").status_code == 401
        assert admin.patch(f"/api/admin/users/{admin_user['id']}", json={"is_active": False}).status_code == 409
def test_custom_session_cookie_supports_desktop_login_and_logout(app):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, session_cookie_name="careark_desktop_session"
    )
    with TestClient(app) as client:
        created = client.post("/api/setup/admin", json={
            "email": "desktop@example.test", "password": "Correct-Horse-42",
        })
        assert created.status_code == 201
        assert "careark_desktop_session" in client.cookies
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401
