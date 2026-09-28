from pathlib import Path

import yaml


def test_compose_has_required_services_and_persistent_data():
    compose = yaml.safe_load(Path("compose.yaml").read_text("utf-8"))
    assert {"web", "worker", "postgres", "minio"} <= set(compose["services"])
    assert compose["services"]["web"]["healthcheck"]
    assert compose["services"]["postgres"]["volumes"]
    assert compose["services"]["minio"]["volumes"]
    assert {"postgres-data", "minio-data"} <= set(compose["volumes"])


def test_example_environment_documents_model_switching_without_secret():
    env = Path(".env.example").read_text("utf-8")
    for key in ["MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME", "MODEL_STRICT_JSON_SCHEMA"]:
        assert f"{key}=" in env
    assert "MODEL_API_KEY=sk-" not in env
