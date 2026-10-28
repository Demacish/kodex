"""The container's entrypoint (kodex.core.entrypoint) and readiness (/readyz)."""

from __future__ import annotations

import sys

import pytest

from kodex.core import entrypoint, migrate


def test_secrets_come_from_files(tmp_path):
    (tmp_path / "secret").write_text("hemligt\n")
    (tmp_path / "other").write_text("två\nrader")
    env = {"SECRET_KEY_FILE": str(tmp_path / "secret"), "SMTP_PASSWORD_FILE": str(tmp_path / "other"),
           "OIDC_CLIENT_SECRET": "redan satt", "OIDC_CLIENT_SECRET_FILE": str(tmp_path / "missing")}  # fmt: skip
    assert entrypoint.load_file_secrets(env) == ["SECRET_KEY", "SMTP_PASSWORD"]
    assert env["SECRET_KEY"] == "hemligt"  # one trailing newline dropped
    assert env["SMTP_PASSWORD"] == "två\nrader"
    assert env["OIDC_CLIENT_SECRET"] == "redan satt"  # a value already set wins (and its file isn't read)


def test_only_settings_come_from_files(tmp_path):
    env = {"KODEX_ENV_FILE": str(tmp_path / "not-a-secret"), "AUTHENTIK_CLIENT_SECRET_FILE": str(tmp_path / "s")}
    (tmp_path / "s").write_text("gammalt namn")
    assert entrypoint.load_file_secrets(env) == ["AUTHENTIK_CLIENT_SECRET"]  # v1's name for a setting counts
    assert "KODEX_ENV" not in env


def test_an_unreadable_secret_file_stops_the_start(tmp_path):
    with pytest.raises(SystemExit, match="NTFY_TOKEN_FILE"):
        entrypoint.load_file_secrets({"NTFY_TOKEN_FILE": str(tmp_path / "nowhere")})


def test_the_commands(monkeypatch):
    assert entrypoint.command(["worker"]) == [sys.executable, "-m", "app.workers.worker"]
    assert entrypoint.command([])[2].startswith("python -m kodex.core.migrate && exec uvicorn")
    assert entrypoint.command(["python", "-m", "kodex.core.backup", "list"]) == [
        "python",
        "-m",
        "kodex.core.backup",
        "list",
    ]


def test_ids_must_be_numbers(monkeypatch):
    monkeypatch.setenv("PUID", "kodex")
    with pytest.raises(SystemExit, match="PUID"):
        entrypoint._id("PUID")
    monkeypatch.setenv("PUID", "")
    assert entrypoint._id("PUID") == 1000


def test_not_ready_until_the_schema_is_at_head(monkeypatch, api):
    client, _ = api
    monkeypatch.setattr(migrate, "head_revision", lambda: "9999")
    answer = client.get("/readyz")
    assert answer.status_code == 503 and "9999" in answer.json()["reason"]
    assert client.get("/healthz").status_code == 200
