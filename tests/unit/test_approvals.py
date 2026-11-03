"""Outbound approval queue: classification, staging, lookup by prefix, expiry, the pause switch."""
from types import SimpleNamespace

import pytest

from kioku.memory import approvals, switch


@pytest.mark.parametrize("tool", [
    "mcp__composio__GMAIL_SEND_EMAIL",
    "mcp__composio__GOOGLEDRIVE_DELETE_FILE",
    "mcp__composio__SLACK_CHAT_POST_MESSAGE",
    "mcp__composio__LINKEDIN_PUBLISH_POST",
    "mcp__bank__transfer_funds",
    "mcp__handoff__browser_task",
])
def test_outbound_tools_are_gated(tool):
    assert approvals.is_outbound(tool) is True


@pytest.mark.parametrize("tool", [
    "mcp__vault__vault_delete",              # the vault is Kioku's own memory
    "mcp__scheduler__schedule_remove",
    "mcp__watch__watch_remove",
    "WebSearch",
    "WebFetch",
    "Agent",
    "mcp__composio__GMAIL_CREATE_EMAIL_DRAFT",
    "mcp__composio__GOOGLECALENDAR_CREATE_EVENT",
    "mcp__composio__GMAIL_FETCH_EMAILS",
])
def test_free_tools_are_not_gated(tool):
    assert approvals.is_outbound(tool) is False


def test_stage_records_and_notifies(fake_redis, no_notify):
    rec = approvals.stage("mcp__composio__GMAIL_SEND_EMAIL",
                          {"to": "anna@example.com", "subject": "Lunch", "body": "Friday?"}, run_id="r1")
    assert len(rec["id"]) == 12
    assert rec["desc"] == "GMAIL_SEND_EMAIL: to=anna@example.com; subject=Lunch; body=Friday?"
    assert approvals.get(rec["id"])["input"]["to"] == "anna@example.com"
    assert approvals.APPROVAL_TTL - 5 < fake_redis.ttl(f"approval:{rec['id']}") <= approvals.APPROVAL_TTL
    assert rec["id"] in no_notify[0] and "NOT run" in no_notify[0]


def test_lookup_by_prefix_then_pop_is_one_shot(fake_redis, no_notify):
    rec = approvals.stage("mcp__x__send", {}, run_id=None)
    assert approvals.get(rec["id"][:6])["id"] == rec["id"]
    assert approvals.pop(rec["id"][:6])["id"] == rec["id"]
    assert approvals.pop(rec["id"]) is None              # cannot be executed twice


def test_reject_removes_and_unknown_ids_are_safe(fake_redis, no_notify):
    rec = approvals.stage("mcp__x__send", {}, run_id=None)
    assert approvals.reject(rec["id"]) is True
    assert approvals.reject(rec["id"]) is False
    assert approvals.get("deadbeef") is None


def test_list_pending_is_newest_first(fake_redis, no_notify, monkeypatch):
    clock = iter([100.0, 200.0])
    monkeypatch.setattr(approvals, "time", SimpleNamespace(time=lambda: next(clock)))
    old = approvals.stage("mcp__x__send", {"to": "a"})
    new = approvals.stage("mcp__x__send", {"to": "b"})
    assert [r["id"] for r in approvals.list_pending()] == [new["id"], old["id"]]


def test_config_edit_is_staged_not_applied(fake_redis, no_notify, vault):
    rec = approvals.stage_config_edit("system/playbook.md", "- be terse", "owner asked for shorter replies")
    assert rec["kind"] == "config-edit"
    assert not (vault / "system/playbook.md").exists()
    assert approvals.get(rec["id"])["content"] == "- be terse"


def test_pause_switch_round_trip(fake_redis):
    assert switch.is_paused() is False
    assert switch.set_paused(True) is True
    assert switch.is_paused() is True
    switch.set_paused(False)
    assert switch.is_paused() is False
