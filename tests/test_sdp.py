"""Classe 100X SDP negotiation tests."""

import base64

import pytest

from custom_components.bticino_c100x.sdp import (
    SRTP_SUITE,
    SdpError,
    build_monitoring_offer,
    build_receive_sdp,
    parse_answer,
)


def _answer(audio_key: bytes, video_key: bytes, *, protocol: str = "RTP/SAVP") -> str:
    return "\r\n".join(
        (
            "v=0",
            "o=- 1 1 IN IP4 198.51.100.20",
            "s=c100x",
            "c=IN IP4 198.51.100.20",
            "t=0 0",
            f"m=audio 5000 {protocol} 8",
            "a=rtpmap:8 PCMA/8000",
            "a=sendrecv",
            f"a=crypto:1 {SRTP_SUITE} inline:{base64.b64encode(audio_key).decode()}",
            f"m=video 6000 {protocol} 96",
            "a=rtpmap:96 H264/90000",
            "a=fmtp:96 packetization-mode=1;profile-level-id=42e01f",
            "a=sendonly",
            f"a=crypto:1 {SRTP_SUITE} inline:{base64.b64encode(video_key).decode()}",
            "",
        )
    )


def test_monitoring_offer_matches_vendor_session_shape() -> None:
    offer = build_monitoring_offer(
        address="203.0.113.10",
        audio_port=41000,
        video_port=42000,
        device_address="visible-eu-uuid",
    )

    assert "a=DEVADDR:visible-eu-uuid\r\n" in offer.sdp
    assert "m=audio 41000 RTP/SAVP 8 0\r\n" in offer.sdp
    assert "a=sendrecv\r\n" in offer.sdp
    assert "m=video 42000 RTP/SAVP 96\r\n" in offer.sdp
    assert "a=recvonly\r\n" in offer.sdp
    assert offer.sdp.count(f" {SRTP_SUITE} inline:") == 2


def test_answer_is_validated_and_receive_sdp_uses_peer_keys() -> None:
    offer = build_monitoring_offer(
        address="203.0.113.10",
        audio_port=41000,
        video_port=42000,
        device_address="eu",
    )
    audio_key = bytes(range(30))
    video_key = bytes(range(30, 60))

    session = parse_answer(_answer(audio_key, video_key), offer)
    receive = build_receive_sdp(session, include_audio=False)

    assert "c=IN IP4 0.0.0.0" in receive
    assert session.audio and session.audio.connection == "198.51.100.20"
    assert session.audio.codec({"pcma"}).payload_type == 8
    assert session.video and session.video.codec({"h264"}).payload_type == 96
    assert "m=audio" not in receive
    assert "m=video 42000 RTP/SAVP 96" in receive
    assert base64.b64encode(video_key).decode() in receive
    assert offer.video_crypto.inline not in receive


def test_offer_advertises_nat_ports_but_receiver_uses_local_ports() -> None:
    offer = build_monitoring_offer(
        address="203.0.113.10",
        audio_port=41000,
        video_port=42000,
        advertised_audio_port=51000,
        advertised_audio_rtcp_port=51005,
        advertised_video_port=52000,
        advertised_video_rtcp_port=52005,
        device_address="eu",
    )
    assert "m=audio 51000 RTP/SAVP" in offer.sdp
    assert "a=rtcp:51005 IN IP4 203.0.113.10" in offer.sdp
    assert "m=video 52000 RTP/SAVP" in offer.sdp
    assert "a=rtcp:52005 IN IP4 203.0.113.10" in offer.sdp

    session = parse_answer(_answer(bytes(30), bytes(30)), offer)
    receive = build_receive_sdp(session, include_audio=False)
    assert "m=video 42000 RTP/SAVP" in receive


def test_answer_rejects_unencrypted_rtp() -> None:
    offer = build_monitoring_offer(
        address="203.0.113.10",
        audio_port=41000,
        video_port=42000,
        device_address="eu",
    )
    with pytest.raises(SdpError, match="mandatory SDES-SRTP"):
        parse_answer(_answer(bytes(30), bytes(30), protocol="RTP/AVP"), offer)


def test_answer_rejects_video_that_will_not_transmit() -> None:
    offer = build_monitoring_offer(
        address="203.0.113.10",
        audio_port=41000,
        video_port=42000,
        device_address="eu",
    )
    answer = _answer(bytes(30), bytes(30)).replace("a=sendonly\r\na=crypto:1", "a=recvonly\r\na=crypto:1")
    with pytest.raises(SdpError, match="video transmission"):
        parse_answer(answer, offer)
