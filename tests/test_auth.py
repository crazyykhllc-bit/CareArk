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
