"""HTTP API: token gating on every data route, open health/dashboard, and task dispatch."""
import pytest
from fastapi.testclient import TestClient

from kioku.api import main as api
from kioku.config import settings


@pytest.fixture
def client(monkeypatch, fake_redis, no_notify):
    dispatched: list[tuple] = []

    class FakeTask:
        def __init__(self, name):
            self.name = name

        def delay(self, *args):
            dispatched.append((self.name, *args))

    for name in ("run_agent_task", "vault_audit_task", "handle_input_task", "reindex_vault_task"):
        monkeypatch.setattr(api, name, FakeTask(name))

    async def create_run(kind, input_, model):
        return "00000000-0000-0000-0000-000000000001"

    async def recent_runs(limit):
        return [{"id": "r1", "kind": "ask"}]

    monkeypatch.setattr(api.db, "create_run", create_run)
    monkeypatch.setattr(api.db, "recent_runs", recent_runs)
    c = TestClient(api.app)
    c.dispatched = dispatched
    return c


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_token", "s3cret-token")
    return "s3cret-token"


def test_health_is_always_open(client, token):
    assert client.get("/health").json() == {"ok": True}


def test_data_routes_require_the_token(client, token):
    assert client.get("/runs").status_code == 401
    assert client.post("/tasks", json={"input": "hi"}).status_code == 401
    assert client.get("/approvals").status_code == 401


@pytest.mark.parametrize("how", ["header", "cookie", "query"])
def test_token_is_accepted_from_each_transport(client, token, how):
    kw = {"header": {"headers": {"Authorization": f"Bearer {token}"}},
          "cookie": {"cookies": {"kioku_token": token}},
          "query": {"params": {"token": token}}}[how]
    if "cookies" in kw:
        client.cookies.set("kioku_token", token)
        kw = {}
    assert client.get("/runs", **kw).status_code == 200


@pytest.mark.parametrize("bad", ["", "s3cret", "s3cret-token-x", "Bearer s3cret-token", "S3CRET-TOKEN"])
def test_wrong_tokens_are_rejected(client, token, bad):
    assert client.get("/runs", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_static_prefix_cannot_be_used_to_skip_auth(client, token):
    assert client.get("/static/../runs").status_code in (401, 404)


@pytest.mark.parametrize(("kind", "task"), [
    ("input", "handle_input_task"),          # natural language → intent router
    ("vault_audit", "vault_audit_task"),
    ("ask", "run_agent_task"),               # raw agent run
])
def test_task_dispatch_routes_by_kind(client, token, kind, task):
    r = client.post("/tasks", json={"kind": kind, "input": "plan my week", "source": "web"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["stream"] == f"/tasks/{r.json()['run_id']}/stream"
    assert client.dispatched[0][0] == task


def test_dashboard_and_its_assets_load_before_sign_in(client, token):
    page = client.get("/")
    assert page.status_code == 200 and "/static/assets/" in page.text
    asset = page.text.split('src="')[1].split('"')[0]
    assert client.get(asset).status_code == 200            # no token needed for the shell
    assert client.get("/status").status_code == 401         # but every data call is gated
