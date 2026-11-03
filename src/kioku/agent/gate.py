"""The permission callbacks every run is wired to (see docs/security/THREAT_MODEL.md)."""


def _sdk_permission_types():
    try:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
    except Exception:  # noqa: BLE001
        return None
    return PermissionResultAllow, PermissionResultDeny


def _outbound_gate(run_id: str):
    """A can_use_tool callback: allow Kioku's own tools and reads, and STAGE anything outbound or
    world-irreversible (memory.approvals → Telegram + command center) instead of running it.

    Fails CLOSED: if classifying or staging raises (Redis down, bad input), the call is denied.
    Returns None if the installed SDK lacks the permission-callback API; the caller then refuses to
    mount any gated tool (see _GATED_SERVERS) rather than running them ungated."""
    types = _sdk_permission_types()
    if types is None:
        return None
    Allow, Deny = types
    from ..memory import approvals

    async def _gate(tool_name, input_data, context):  # signature per SDK CanUseTool
        try:
            if not approvals.is_outbound(tool_name, input_data):
                return Allow()
            rec = approvals.stage(tool_name, input_data, run_id=run_id)
        except Exception as e:  # noqa: BLE001
            return Deny(message=f"Blocked: the approval gate could not evaluate this call ({type(e).__name__}). "
                                "It did NOT run. Tell the owner it needs a manual step.")
        return Deny(message=(
            f"OUTBOUND action staged for the user's approval (id {rec['id']}); it did NOT run and you "
            "must not retry it. Tell them plainly what you queued. If it's an email/message, ALSO "
            "prepare it as a DRAFT now so it's ready the moment they approve."))

    return _gate


def _approved_call_gate(approved_call: dict):
    """Gate for executing ONE owner-approved action: that exact tool with those exact arguments,
    once. Everything else is denied — the approved arguments may themselves carry injected text,
    so the run gets no other capability. None if the SDK lacks the callback API."""
    types = _sdk_permission_types()
    if types is None:
        return None
    Allow, Deny = types
    want_tool, want_input = approved_call["tool"], approved_call.get("input") or {}
    used = {"done": False}

    async def _gate(tool_name, input_data, context):
        if tool_name == want_tool and (input_data or {}) == want_input and not used["done"]:
            used["done"] = True
            return Allow()
        return Deny(message="Only the single approved call may run in this session.")

    return _gate
