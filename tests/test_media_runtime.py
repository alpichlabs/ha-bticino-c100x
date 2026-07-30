"""Tests for bounded G.711 SRTP media handling."""

import base64
from unittest.mock import MagicMock

import pylibsrtp
from aiortc.rtp import RtpPacket

from custom_components.bticino_c100x.media_runtime import AudioRtpProtocol
from custom_components.bticino_c100x.sdp import (
    SRTP_SUITE,
    build_monitoring_offer,
    parse_answer,
)


def _session():
    offer = build_monitoring_offer(
        address="127.0.0.1",
        audio_port=41000,
        video_port=42000,
        device_address="eu",
    )
    audio_key = bytes(range(30))
    video_key = bytes(range(30, 60))
    answer = "\r\n".join(
        (
            "v=0",
            "o=- 1 1 IN IP4 127.0.0.1",
            "s=c100x",
            "c=IN IP4 127.0.0.1",
            "t=0 0",
            "m=audio 5000 RTP/SAVP 8",
            "a=rtpmap:8 PCMA/8000",
            "a=sendrecv",
            f"a=crypto:1 {SRTP_SUITE} inline:{base64.b64encode(audio_key).decode()}",
            "m=video 6000 RTP/SAVP 96",
            "a=rtpmap:96 H264/90000",
            "a=sendonly",
            f"a=crypto:1 {SRTP_SUITE} inline:{base64.b64encode(video_key).decode()}",
            "",
        )
    )
    return parse_answer(answer, offer)


def _session_for(key: bytes, inbound: bool) -> pylibsrtp.Session:
    policy = pylibsrtp.Policy(
        key=key,
        ssrc_type=(
            pylibsrtp.Policy.SSRC_ANY_INBOUND
            if inbound
            else pylibsrtp.Policy.SSRC_ANY_OUTBOUND
        ),
        srtp_profile=pylibsrtp.Policy.SRTP_PROFILE_AES128_CM_SHA1_80,
    )
    return pylibsrtp.Session(policy)


def test_microphone_is_silent_until_explicitly_enabled() -> None:
    session = _session()
    protocol = AudioRtpProtocol(MagicMock())
    transport = MagicMock()
    protocol.connection_made(transport)
    protocol.configure(session)

    protocol.send_pcm(bytes(320))
    transport.sendto.assert_not_called()

    protocol.set_microphone(True)
    protocol.send_pcm(bytes(320))

    protected, remote = transport.sendto.call_args.args
    plain = _session_for(session.offer.audio_crypto.key, inbound=True).unprotect(protected)
    packet = RtpPacket.parse(plain)
    assert packet.payload_type == 8
    assert len(packet.payload) == 160
    assert remote == ("127.0.0.1", 5000)


async def test_received_srtp_is_decrypted_into_pcm_track() -> None:
    session = _session()
    received = MagicMock()
    protocol = AudioRtpProtocol(received)
    protocol.connection_made(MagicMock())
    protocol.configure(session)
    packet = RtpPacket(
        payload_type=8,
        sequence_number=1,
        timestamp=160,
        ssrc=1234,
        payload=bytes([0xD5]) * 160,
    )
    protected = _session_for(session.audio.crypto.key, inbound=False).protect(packet.serialize())

    protocol.datagram_received(protected, ("127.0.0.1", 5000))
    frame = await protocol.track.recv()

    assert frame.samples == 160
    assert frame.sample_rate == 8000
    assert frame.pts == 160
    received.assert_called_once_with()
