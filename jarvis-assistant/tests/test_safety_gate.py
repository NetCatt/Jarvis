import time
from tools.safety_gate import evaluate_tool_safety, handle_pending_confirmation

def test_safety_gate_denylist_blocks():
    status, msg = evaluate_tool_safety("run_terminal", {"command": "format C:"})
    assert status == "BLOCKED"
    assert "safety policy" in msg

    status, msg = evaluate_tool_safety("run_terminal", {"command": "del /s /q important.txt"})
    assert status == "BLOCKED"

    status, msg = evaluate_tool_safety("run_terminal", {"command": "regedit.exe"})
    assert status == "BLOCKED"

    status, msg = evaluate_tool_safety("run_terminal", {"command": "powershell -enc aXN4"})
    assert status == "BLOCKED"

def test_safety_gate_high_risk_confirm():
    status, msg = evaluate_tool_safety("os_input", {"keys": ["ctrl", "w"]})
    assert status == "CONFIRM"
    assert "close" in msg.lower()

    handled, reply = handle_pending_confirmation("no")
    assert handled is True
    assert "Cancelled" in reply

def test_safety_gate_confirm_execution():
    status, msg = evaluate_tool_safety("os_input", {"keys": ["alt", "f4"]})
    assert status == "CONFIRM"

    handled, reply = handle_pending_confirmation("yes")
    assert handled is True
    assert "Done" in reply or "Executed" in reply

def test_safety_gate_timeout():
    status, msg = evaluate_tool_safety("os_input", {"keys": ["ctrl", "w"]})
    assert status == "CONFIRM"

    from tools import safety_gate
    safety_gate._PENDING_ACTION["time"] = time.time() - 10.0

    handled, reply = handle_pending_confirmation("yes")
    assert handled is False
    assert reply is None
