"""
tests/test_cloud_client.py

Tests for the dashboard's API client helpers that need no network:
call_api is replaced with a fake, so nothing leaves the machine.
"""

import cloud_client


def test_fetch_history_flattens_and_quotes_resource_ids(monkeypatch):
    calls = []

    def fake_call_api(api_url, id_token, method, path):
        calls.append((method, path))
        return {"history": [{"resource_id": path, "n": i} for i in range(3)]}

    monkeypatch.setattr(cloud_client, "call_api", fake_call_api)
    history = cloud_client.fetch_history("https://api", "tok", ["sg-1", "arn:aws:iam::1:role/x"])
    assert len(history) == 6
    assert calls == [("GET", "/findings/sg-1"), ("GET", "/findings/arn%3Aaws%3Aiam%3A%3A1%3Arole%2Fx")]


def test_fetch_history_respects_limit(monkeypatch):
    monkeypatch.setattr(cloud_client, "call_api",
                        lambda *a: {"history": [{"n": i} for i in range(10)]})
    assert len(cloud_client.fetch_history("u", "t", ["a"], limit_per_resource=4)) == 4


def test_fetch_history_missing_history_key(monkeypatch):
    monkeypatch.setattr(cloud_client, "call_api", lambda *a: {})
    assert cloud_client.fetch_history("u", "t", ["a"]) == []


def test_load_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_client, "OUTPUTS_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("IDG_API_URL", "https://example.test")
    monkeypatch.setenv("IDG_COGNITO_CLIENT_ID", "abc")
    monkeypatch.delenv("IDG_REGION", raising=False)
    cfg = cloud_client.load_config()
    assert cfg == {"api_url": "https://example.test", "client_id": "abc", "region": "ap-southeast-2"}
