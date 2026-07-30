"""Shared WebRTC connectivity configuration."""

# Keep two independent STUN providers so a transient DNS or UDP failure does not
# make remote camera viewing depend on host-only ICE candidates.
STUN_URLS = (
    "stun:stun.cloudflare.com:3478",
    "stun:stun.cloudflare.com:53",
    "stun:stun.linphone.org:3478",
)

# aiortc supports only one STUN server even when RTCIceServer contains a list.
# Use the same service as the vendor Classe 100X app for the VPS-side mapping.
SERVER_STUN_URL = "stun:stun.linphone.org:3478"
