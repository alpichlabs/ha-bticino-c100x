"""Monitoring state-machine tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bticino_c100x.media_session import MediaSession, SessionState


async def test_start_mutes_before_opening_vendor_session() -> None:
    runtime = MagicMock()
    calls = []
    runtime.set_microphone = AsyncMock(side_effect=lambda enabled: calls.append(("mic", enabled)))
    runtime.start_monitoring = AsyncMock(
        side_effect=lambda address, *_args: calls.append(("start", address))
    )
    session = MediaSession(runtime, MagicMock())

    await session.start("eu-uuid")

    assert calls == [("mic", False), ("start", "eu-uuid")]
    assert session.state == SessionState.CONNECTING
    assert session.microphone_enabled is False


async def test_end_mutes_before_terminating() -> None:
    runtime = MagicMock()
    calls = []
    runtime.set_microphone = AsyncMock(side_effect=lambda enabled: calls.append(("mic", enabled)))
    runtime.end_session = AsyncMock(side_effect=lambda: calls.append(("end", None)))
    session = MediaSession(runtime, MagicMock())
    session.state = SessionState.STREAMING
    session.microphone_enabled = True

    await session.end()

    assert calls == [("mic", False), ("end", None)]
    assert session.state == SessionState.IDLE
    assert session.microphone_enabled is False


async def test_microphone_cannot_enable_without_stream() -> None:
    runtime = MagicMock()
    runtime.set_microphone = AsyncMock()
    session = MediaSession(runtime, MagicMock())

    with pytest.raises(RuntimeError, match="active media session"):
        await session.set_microphone(True)

    runtime.set_microphone.assert_not_awaited()


def test_call_error_resets_microphone_and_records_error() -> None:
    session = MediaSession(MagicMock(), MagicMock())
    session.state = SessionState.STREAMING
    session.microphone_enabled = True

    session.handle_event({"event": "call_state", "state": "error"})

    assert session.state == SessionState.ERROR
    assert session.microphone_enabled is False
    assert session.last_error == "call_error"
