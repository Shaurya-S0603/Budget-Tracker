from __future__ import annotations

import streamlit as st

import storage


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_generic_github_token_does_not_override_streamlit_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "platform-token-with-wrong-repo-access")
    monkeypatch.delenv("BUDGET_TRACKER_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        st,
        "secrets",
        {
            "github": {
                "token": "streamlit-app-token",
                "repo": "Shaurya-S0603/Budget-Tracker",
                "branch": "main",
                "db_path": "data/expenses.db",
            }
        },
    )

    config = storage.github_config()
    assert config["token"] == "streamlit-app-token"


def test_rejected_token_can_still_read_missing_file_from_public_repo(monkeypatch):
    config = {
        "enabled": True,
        "token": "expired-token",
        "repo": "Shaurya-S0603/Budget-Tracker",
        "branch": "main",
        "db_path": "data/expenses.db",
    }
    calls: list[bool] = []

    def fake_request(method, request_config, *, authenticated=True, **kwargs):
        assert method == "GET"
        assert request_config is config
        calls.append(authenticated)
        return FakeResponse(401 if authenticated else 404)

    monkeypatch.setattr(storage, "_safe_request", fake_request)
    assert storage._read_remote_file(config) == (None, None)
    assert calls == [True, False]
