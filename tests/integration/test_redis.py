"""Approvals and the pause switch on a real Redis: TTL, prefix lookup via SCAN, one-shot pop."""
from kioku.memory import approvals, switch


def test_staged_action_has_a_ttl_and_is_one_shot(real_redis, no_notify):
    rec = approvals.stage("mcp__composio__GMAIL_SEND_EMAIL", {"to": "anna@example.com"}, run_id="r1")
    assert 0 < real_redis.ttl(f"approval:{rec['id']}") <= approvals.APPROVAL_TTL
    assert approvals.get(rec["id"][: approvals.MIN_PREFIX])["tool"] == "mcp__composio__GMAIL_SEND_EMAIL"
    assert approvals.pop(rec["id"]) is not None
    assert approvals.pop(rec["id"]) is None
    assert approvals.list_pending() == []


def test_many_pending_actions_are_listed(real_redis, no_notify):
    ids = {approvals.stage("mcp__x__send", {"n": i})["id"] for i in range(25)}
    assert {r["id"] for r in approvals.list_pending()} == ids


def test_pause_switch_is_shared_state(real_redis):
    switch.set_paused(True)
    assert real_redis.get("kioku:paused") == b"1"
    assert switch.is_paused() is True
    switch.set_paused(False)
    assert switch.is_paused() is False
