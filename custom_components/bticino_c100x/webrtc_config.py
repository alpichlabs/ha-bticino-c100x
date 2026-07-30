"""Shared WebRTC connectivity configuration."""

# Keep two independent STUN providers so a transient DNS or UDP failure does not
# make remote camera viewing depend on host-only ICE candidates.
STUN_URLS = (
    "stun:stun.cloudflare.com:3478",
    "stun:stun.cloudflare.com:53",
    "stun:stun.linphone.org:3478",
)
