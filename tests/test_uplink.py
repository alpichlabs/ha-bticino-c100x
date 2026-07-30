"""Browser microphone safety-order tests."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.bticino_c100x.uplink import MicrophoneUplink


async def test_uplink_mutes_before_browser_peer_closes() -> None:
    calls = []
    session = MagicMock()
    session.microphone_enabled = True
    session.set_microphone = AsyncMock(side_effect=lambda enabled: calls.append(("mic", enabled)))
    uplink = MicrophoneUplink(session)
    uplink.owner = "viewer"
    uplink.peer = MagicMock()
    uplink.peer.close = AsyncMock(side_effect=lambda: calls.append(("close", None)))

    await uplink.close("viewer")

    assert calls == [("mic", False), ("close", None)]
    assert uplink.owner is None
