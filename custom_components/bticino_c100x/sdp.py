"""Small, strict SDP model for Classe 100X monitoring calls."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field

SRTP_SUITE = "AES_CM_128_HMAC_SHA1_80"
SRTP_KEY_BYTES = 30


class SdpError(ValueError):
    """The peer returned an unusable media description."""


@dataclass(frozen=True, slots=True)
class CryptoAttribute:
    """One SDES-SRTP crypto attribute."""

    tag: int
    suite: str
    key: bytes

    @property
    def inline(self) -> str:
        return base64.b64encode(self.key).decode("ascii")


@dataclass(frozen=True, slots=True)
class Codec:
    """One RTP payload mapping."""

    payload_type: int
    name: str
    clock_rate: int
    channels: int = 1
    fmtp: str | None = None


@dataclass(slots=True)
class MediaDescription:
    """Negotiated media section."""

    kind: str
    port: int
    protocol: str
    connection: str
    direction: str = "sendrecv"
    codecs: list[Codec] = field(default_factory=list)
    crypto: CryptoAttribute | None = None

    def codec(self, names: set[str]) -> Codec | None:
        return next((item for item in self.codecs if item.name.casefold() in names), None)


@dataclass(slots=True)
class MonitoringOffer:
    """Locally generated offer and the secrets needed for outbound media."""

    sdp: str
    address: str
    audio_port: int
    video_port: int
    advertised_audio_port: int
    advertised_video_port: int
    audio_crypto: CryptoAttribute
    video_crypto: CryptoAttribute


@dataclass(slots=True)
class NegotiatedSession:
    """Validated answer together with our offer state."""

    offer: MonitoringOffer
    audio: MediaDescription | None
    video: MediaDescription | None


def new_crypto() -> CryptoAttribute:
    """Create a fresh SDES key for one media direction."""
    return CryptoAttribute(1, SRTP_SUITE, secrets.token_bytes(SRTP_KEY_BYTES))


def build_monitoring_offer(
    *,
    address: str,
    audio_port: int,
    video_port: int,
    device_address: str,
    advertised_audio_port: int | None = None,
    advertised_audio_rtcp_port: int | None = None,
    advertised_video_port: int | None = None,
    advertised_video_rtcp_port: int | None = None,
) -> MonitoringOffer:
    """Build the verified Classe 100X monitoring shape with mandatory SRTP."""
    audio_crypto = new_crypto()
    video_crypto = new_crypto()
    public_audio = advertised_audio_port or audio_port
    public_audio_rtcp = advertised_audio_rtcp_port or public_audio + 1
    public_video = advertised_video_port or video_port
    public_video_rtcp = advertised_video_rtcp_port or public_video + 1
    session_id = secrets.randbits(63)
    lines = [
        "v=0",
        f"o=- {session_id} {session_id} IN IP4 {address}",
        "s=BTicino Classe 100X",
        f"c=IN IP4 {address}",
        "t=0 0",
        f"a=DEVADDR:{device_address}",
        f"m=audio {public_audio} RTP/SAVP 8 0",
        f"a=rtcp:{public_audio_rtcp} IN IP4 {address}",
        "a=rtpmap:8 PCMA/8000",
        "a=rtpmap:0 PCMU/8000",
        "a=sendrecv",
        f"a=crypto:1 {SRTP_SUITE} inline:{audio_crypto.inline}",
        f"m=video {public_video} RTP/SAVP 96",
        f"a=rtcp:{public_video_rtcp} IN IP4 {address}",
        "a=rtpmap:96 H264/90000",
        "a=fmtp:96 packetization-mode=1;profile-level-id=42e01f",
        "a=recvonly",
        f"a=crypto:1 {SRTP_SUITE} inline:{video_crypto.inline}",
    ]
    return MonitoringOffer(
        sdp="\r\n".join(lines) + "\r\n",
        address=address,
        audio_port=audio_port,
        video_port=video_port,
        advertised_audio_port=public_audio,
        advertised_video_port=public_video,
        audio_crypto=audio_crypto,
        video_crypto=video_crypto,
    )


def parse_answer(value: bytes | str, offer: MonitoringOffer) -> NegotiatedSession:
    """Parse and validate the media portions required by this integration."""
    text = value.decode("utf-8", errors="strict") if isinstance(value, bytes) else value
    session_connection = ""
    current: dict | None = None
    sections: list[dict] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("m="):
            parts = line[2:].split()
            if len(parts) < 4:
                raise SdpError("Malformed SDP media line")
            try:
                port = int(parts[1].split("/", 1)[0])
                payloads = [int(item) for item in parts[3:]]
            except ValueError as err:
                raise SdpError("Malformed SDP media value") from err
            current = {
                "kind": parts[0],
                "port": port,
                "protocol": parts[2],
                "payloads": payloads,
                "connection": session_connection,
                "direction": "sendrecv",
                "rtpmap": {},
                "fmtp": {},
                "crypto": None,
            }
            sections.append(current)
            continue
        if line.startswith("c="):
            parts = line[2:].split()
            if len(parts) != 3 or parts[0] != "IN" or parts[1] not in {"IP4", "IP6"}:
                raise SdpError("Unsupported SDP connection")
            if current is None:
                session_connection = parts[2]
            else:
                current["connection"] = parts[2]
            continue
        if current is None or not line.startswith("a="):
            continue
        attribute = line[2:]
        if attribute in {"sendrecv", "sendonly", "recvonly", "inactive"}:
            current["direction"] = attribute
        elif attribute.startswith("rtpmap:"):
            payload, mapping = attribute[7:].split(None, 1)
            fields = mapping.split("/")
            current["rtpmap"][int(payload)] = (
                fields[0],
                int(fields[1]),
                int(fields[2]) if len(fields) > 2 else 1,
            )
        elif attribute.startswith("fmtp:"):
            payload, parameters = attribute[5:].split(None, 1)
            current["fmtp"][int(payload)] = parameters
        elif attribute.startswith("crypto:"):
            tag_and_rest = attribute[7:].split(None, 2)
            if len(tag_and_rest) < 3 or not tag_and_rest[2].startswith("inline:"):
                raise SdpError("Unsupported SRTP key parameters")
            key_value = tag_and_rest[2][7:].split("|", 1)[0]
            try:
                key = base64.b64decode(key_value, validate=True)
            except ValueError as err:
                raise SdpError("Invalid SRTP key") from err
            current["crypto"] = CryptoAttribute(int(tag_and_rest[0]), tag_and_rest[1], key)

    parsed: dict[str, MediaDescription] = {}
    for section in sections:
        if section["kind"] not in {"audio", "video"} or section["port"] == 0:
            continue
        if section["protocol"].upper() != "RTP/SAVP":
            raise SdpError(f"{section['kind'].title()} did not negotiate mandatory SDES-SRTP")
        crypto = section["crypto"]
        if crypto is None or crypto.suite != SRTP_SUITE or len(crypto.key) != SRTP_KEY_BYTES:
            raise SdpError(f"{section['kind'].title()} returned unsupported SRTP parameters")
        if not section["connection"]:
            raise SdpError(f"{section['kind'].title()} has no connection address")
        codecs = []
        for payload in section["payloads"]:
            mapping = section["rtpmap"].get(payload)
            if mapping is None:
                if payload == 0:
                    mapping = ("PCMU", 8000, 1)
                elif payload == 8:
                    mapping = ("PCMA", 8000, 1)
                else:
                    continue
            codecs.append(Codec(payload, *mapping, section["fmtp"].get(payload)))
        parsed[section["kind"]] = MediaDescription(
            kind=section["kind"],
            port=section["port"],
            protocol=section["protocol"],
            connection=section["connection"],
            direction=section["direction"],
            codecs=codecs,
            crypto=crypto,
        )

    audio = parsed.get("audio")
    video = parsed.get("video")
    if video is None or video.codec({"h264"}) is None:
        raise SdpError("The external unit did not negotiate H.264 video")
    if video.direction not in {"sendonly", "sendrecv"}:
        raise SdpError("The external unit did not enable video transmission")
    if audio is not None and audio.codec({"pcma", "pcmu"}) is None:
        raise SdpError("The external unit selected an unsupported audio codec")
    return NegotiatedSession(offer=offer, audio=audio, video=video)


def build_receive_sdp(session: NegotiatedSession, *, include_audio: bool = True) -> str:
    """Describe the local receive ports using the peer's outbound SRTP keys."""
    lines = [
        "v=0",
        "o=- 0 0 IN IP4 0.0.0.0",
        "s=BTicino Classe 100X receive",
        "c=IN IP4 0.0.0.0",
        "t=0 0",
    ]
    for media, local_port in (
        (session.audio, session.offer.audio_port),
        (session.video, session.offer.video_port),
    ):
        if media is None or media.crypto is None:
            continue
        if media.kind == "audio" and not include_audio:
            continue
        payloads = " ".join(str(codec.payload_type) for codec in media.codecs)
        lines.append(f"m={media.kind} {local_port} RTP/SAVP {payloads}")
        for codec in media.codecs:
            channels = f"/{codec.channels}" if codec.channels != 1 else ""
            lines.append(
                f"a=rtpmap:{codec.payload_type} {codec.name}/{codec.clock_rate}{channels}"
            )
            if codec.fmtp:
                lines.append(f"a=fmtp:{codec.payload_type} {codec.fmtp}")
        lines.append("a=recvonly")
        lines.append(
            f"a=crypto:{media.crypto.tag} {media.crypto.suite} inline:{media.crypto.inline}"
        )
    return "\r\n".join(lines) + "\r\n"
