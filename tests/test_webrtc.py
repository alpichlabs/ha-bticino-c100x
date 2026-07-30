"""Tests for WebRTC candidate lifecycle."""

from types import SimpleNamespace

import pytest

from custom_components.bticino_c100x.webrtc import WebRTCBridge
from custom_components.bticino_c100x.webrtc_config import STUN_URLS


def test_stun_has_independent_fallback() -> None:
    assert STUN_URLS == (
        "stun:stun.cloudflare.com:3478",
        "stun:stun.linphone.org:3478",
    )


@pytest.mark.asyncio
async def test_candidates_are_queued_during_sip_setup() -> None:
    """Trickled candidates must survive until the peer has its offer."""
    bridge = WebRTCBridge.__new__(WebRTCBridge)
    bridge._peers = {}
    bridge._pending_candidates = {}
    candidate = SimpleNamespace(candidate="candidate:1 1 UDP 1 192.0.2.1 1234 typ host")
    completed = SimpleNamespace(candidate="")

    bridge.prepare("browser-session")
    await bridge.add_candidate("browser-session", candidate)
    await bridge.add_candidate("browser-session", completed)

    assert bridge._pending_candidates["browser-session"] == [candidate, completed]
    assert len(bridge._pending_candidates["browser-session"]) == 2


@pytest.mark.asyncio
async def test_unknown_candidate_is_not_retained() -> None:
    bridge = WebRTCBridge.__new__(WebRTCBridge)
    bridge._peers = {}
    bridge._pending_candidates = {}

    await bridge.add_candidate(
        "unknown", SimpleNamespace(candidate="candidate:1 1 UDP 1 192.0.2.1 1234 typ host")
    )

    assert bridge._pending_candidates == {}
