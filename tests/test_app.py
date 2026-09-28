from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


def test_health_is_available_without_model_key():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_model_status_reports_unconfigured():
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        model_api_key="",
        model_name="",
    )
    client = TestClient(app)

    response = client.get("/api/system/status")

    assert response.status_code == 200
    assert response.json()["model"] == {"configured": False, "fallback_configured": False, "fallback2_configured": False}


def test_model_status_reports_complete_backup_without_exposing_its_key():
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        model_api_key="primary-secret", model_name="primary-vision",
        model_fallback_base_url="https://backup.test/v1",
        model_fallback_api_key="backup-secret", model_fallback_name="backup-vision",
    )
    response = TestClient(app).get("/api/system/status")
    assert response.json() == {"model": {"configured": True, "fallback_configured": True, "fallback2_configured": False}}


def test_model_status_second_backup_never_exposes_credentials():
    app=create_app()
    app.dependency_overrides[get_settings]=lambda:Settings(_env_file=None,model_api_key='primary-secret',model_name='vision',model_fallback2_base_url='https://deep.test',model_fallback2_api_key='second-secret',model_fallback2_name='deepseek-flash')
    response=TestClient(app).get('/api/system/status')
    assert response.json()['model']['fallback2_configured'] is True
    assert 'second-secret' not in response.text
