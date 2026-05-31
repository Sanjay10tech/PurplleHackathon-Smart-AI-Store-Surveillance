"""Deployment manifest smoke tests (no Docker daemon required)."""

# PROMPT:
# Generate complete pytest suite — deployment manifest smoke tests (no Docker daemon).
#
# CHANGES MADE:
# - Validates docker-compose.yml, Dockerfile entrypoint, and .env.example presence.

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_docker_compose_exists() -> None:
    assert (ROOT / "docker-compose.yml").is_file()


def test_docker_compose_defines_postgres_and_api() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgres:" in text
    assert "  api:" in text
    assert "healthcheck:" in text
    assert "service_healthy" in text
    assert "docker-entrypoint.sh" not in text  # invoked via Dockerfile ENTRYPOINT


def test_dockerfile_and_entrypoint_exist() -> None:
    assert (ROOT / "Dockerfile").is_file()
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "docker_entrypoint.py" in dockerfile
    assert (ROOT / "scripts" / "docker_entrypoint.py").is_file()
    assert (ROOT / "scripts" / "wait_for_database.py").is_file()
    assert (ROOT / "scripts" / "healthcheck.py").is_file()


def test_env_example_documents_database_url() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DATABASE_URL=" in env_example
    assert "POSTGRES_USER=" in env_example
