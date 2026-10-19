"""Explicit foreground recovery must discover hidden windows without weakening targeting."""
from unittest.mock import MagicMock

import pytest

from tools.computer_use.backend import ActionResult
from tools.computer_use.cua_backend import CuaDriverBackend


def make_backend(*, count=1, recovered=True, allowed=True, app_name="Calculator"):
    backend = CuaDriverBackend()
    session = backend._session = MagicMock()
    raised = False
    windows = [{"app_name": app_name, "pid": 123, "window_id": 90 + i, "is_on_screen": False} for i in range(count)]

    def call(name, args):
        if name == "list_windows":
            rows = windows if not args["on_screen_only"] else ([{**windows[0], "is_on_screen": True}] if raised and recovered else [])
            return {"structuredContent": {"windows": rows}, "isError": False}
        if name == "list_apps":
            return {"structuredContent": {"apps": [{"name": app_name, "bundle_id": "com.apple.calculator", "pid": 123, "running": True}]}, "isError": False}
        raise AssertionError(name)

    def bring_to_front(**kwargs):
        nonlocal raised
        assert kwargs == {"pid": 123, "window_id": 90}
        raised = True
        return ActionResult(ok=allowed, action="bring_to_front", code="ok" if allowed else "permission_denied")

    session.call_tool.side_effect = call
    session._call_tool_via_cli.side_effect = lambda name, args, timeout: call(name, args)
    backend.bring_to_front = MagicMock(side_effect=bring_to_front)
    return backend


def test_hidden_window_requires_explicit_raise_and_verified_recovery():
    backend = make_backend()
    original = backend._match_windows_for_app
    # Existing hosts wrap this selector using its original two-argument contract.
    backend._match_windows_for_app = lambda windows, app: original(windows, app)
    assert not backend.focus_app("com.apple.calculator").ok
    backend.bring_to_front.assert_not_called()
    assert all(call.args[1]["on_screen_only"] for call in backend._session.call_tool.call_args_list if call.args[0] == "list_windows")
    assert backend.focus_app("com.apple.calculator", raise_window=True).ok
    backend.bring_to_front.assert_called_once_with(pid=123, window_id=90)
    assert backend._active_window_id == 90


@pytest.mark.parametrize("options,expected", [
    ({"count": 2}, "ambiguous_recovery_target"),
    ({"recovered": False}, "window_recovery_unverified"),
    ({"allowed": False}, "permission_denied"),
])
def test_failed_recovery_disarms_previous_target(options, expected):
    backend = make_backend(**options)
    backend._active_pid, backend._active_window_id = 999, 999
    result = backend.focus_app("com.apple.calculator", raise_window=True)
    assert not result.ok and result.code == expected
    assert backend._active_pid is None and backend._active_window_id is None
    if options.get("count") == 2:
        backend.bring_to_front.assert_not_called()


def test_hidden_recovery_never_uses_a_partial_app_name_match():
    backend = make_backend(app_name="Another Calculator")
    assert not backend.focus_app("Calculator", raise_window=True).ok
    backend.bring_to_front.assert_not_called()


def test_unsupported_recovery_does_not_arm_a_hidden_target():
    backend = make_backend()
    backend._session._has_tool.return_value = False
    result = backend.focus_app("com.apple.calculator", raise_window=True)
    assert not result.ok and result.code == "bring_to_front_unsupported"
    assert backend._active_pid is None and backend._active_window_id is None
    backend.bring_to_front.assert_not_called()


def test_window_name_cannot_bypass_host_scoped_app_discovery():
    backend = make_backend()
    backend.list_apps = lambda: []
    assert not backend.focus_app("Calculator", raise_window=True).ok
    backend.bring_to_front.assert_not_called()
