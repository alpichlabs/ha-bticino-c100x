"""Credential-free loopback validation of FFmpeg's Classe 100X media path."""

import base64
import os
import select
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

import av
import pytest

from custom_components.bticino_c100x.sdp import SRTP_SUITE


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or os.environ.get("RUN_FFMPEG_SRTP_SMOKE") != "1",
    reason="credential-free UDP smoke test is run explicitly in CI",
)
def test_ffmpeg_decrypts_h264_srtp_from_generated_sdp(tmp_path, socket_enabled) -> None:
    """Exercise the same SDP/SRTP demux used at runtime."""
    ffmpeg = shutil.which("ffmpeg")
    for port in range(42000, 52000, 2):
        first = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        second = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            first.bind(("127.0.0.1", port))
            second.bind(("127.0.0.1", port + 1))
            break
        except OSError:
            first.close()
            second.close()
    else:
        raise AssertionError("No local RTP port pair is available")
    first.close()
    second.close()
    key = base64.b64encode(bytes(range(30))).decode()
    sdp = tmp_path / "receive.sdp"
    sdp.write_text(
        "\r\n".join(
            (
                "v=0",
                "o=- 0 0 IN IP4 127.0.0.1",
                "s=loopback",
                "c=IN IP4 127.0.0.1",
                "t=0 0",
                f"m=video {port} RTP/SAVP 96",
                "a=rtpmap:96 H264/90000",
                "a=fmtp:96 packetization-mode=1;profile-level-id=42e01f",
                f"a=crypto:1 {SRTP_SUITE} inline:{key}",
                "",
            )
        )
    )
    receiver = subprocess.Popen(
        (
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file,udp,rtp,srtp",
            "-analyzeduration",
            "0",
            "-probesize",
            "32",
            "-f",
            "sdp",
            "-i",
            str(sdp),
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "rawvideo",
            "pipe:1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1)
        sender = subprocess.run(
            (
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-re",
                "-i",
                "testsrc=size=160x120:rate=5",
                "-frames:v",
                "10",
                "-c:v",
                "libx264",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-payload_type",
                "96",
                "-f",
                "rtp",
                "-srtp_out_suite",
                SRTP_SUITE,
                "-srtp_out_params",
                key,
                f"srtp://127.0.0.1:{port}",
            ),
            check=False,
            capture_output=True,
            timeout=10,
        )
        assert sender.returncode == 0, sender.stderr.decode(errors="replace")
        assert receiver.stdout
        ready, _, _ = select.select((receiver.stdout,), (), (), 5)
        if not ready:
            receiver.kill()
            _, details = receiver.communicate(timeout=2)
            raise AssertionError(details.decode(errors="replace"))
        frame = os.read(receiver.stdout.fileno(), 160 * 120 * 3 // 2)
        assert len(frame) == 160 * 120 * 3 // 2
    finally:
        if receiver.poll() is None:
            receiver.terminate()
            try:
                receiver.wait(timeout=2)
            except subprocess.TimeoutExpired:
                receiver.kill()
                receiver.wait(timeout=2)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or os.environ.get("RUN_FFMPEG_SRTP_SMOKE") != "1",
    reason="credential-free UDP smoke test is run explicitly in CI",
)
def test_ffmpeg_loopback_relay_allows_late_pyav_viewer(tmp_path, socket_enabled) -> None:
    """Prove FFmpeg receives before a later Home Assistant viewer attaches."""
    ffmpeg = shutil.which("ffmpeg")
    ports = []
    for port in range(52000, 62000, 2):
        first = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        second = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            first.bind(("127.0.0.1", port))
            second.bind(("127.0.0.1", port + 1))
            ports.append(port)
            first.close()
            second.close()
            if len(ports) == 2:
                break
        except OSError:
            first.close()
            second.close()
    else:
        if len(ports) < 2:
            raise AssertionError("Two local RTP port pairs are required")
    source_port, relay_port = ports
    key = base64.b64encode(bytes(range(30))).decode()
    receive_sdp = tmp_path / "receive.sdp"
    playback_sdp = tmp_path / "playback.sdp"
    receive_sdp.write_text(
        "\r\n".join(
            (
                "v=0",
                "o=- 0 0 IN IP4 127.0.0.1",
                "s=loopback",
                "c=IN IP4 127.0.0.1",
                "t=0 0",
                f"m=video {source_port} RTP/SAVP 96",
                "a=rtpmap:96 H264/90000",
                "a=fmtp:96 packetization-mode=1;profile-level-id=42e01f",
                f"a=crypto:1 {SRTP_SUITE} inline:{key}",
                "",
            )
        )
    )
    playback_sdp.write_text(
        "\r\n".join(
            (
                "v=0",
                "o=- 0 0 IN IP4 127.0.0.1",
                "s=loopback relay",
                "c=IN IP4 127.0.0.1",
                "t=0 0",
                f"m=video {relay_port} RTP/AVP 96",
                "a=rtpmap:96 H264/90000",
                "a=fmtp:96 packetization-mode=1;profile-level-id=42e01f",
                "",
            )
        )
    )
    relay = subprocess.Popen(
        (
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file,udp,rtp,srtp",
            "-analyzeduration",
            "0",
            "-probesize",
            "32",
            "-f",
            "sdp",
            "-i",
            str(receive_sdp),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-payload_type",
            "96",
            "-f",
            "rtp",
            "-y",
            f"rtp://127.0.0.1:{relay_port}?rtcpport={relay_port + 1}&pkt_size=1200",
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    def read_frame() -> tuple[int, int]:
        with av.open(
            str(playback_sdp),
            format="sdp",
            options={
                "protocol_whitelist": "file,udp,rtp",
                "analyzeduration": "0",
                "probesize": "32",
            },
        ) as container:
            for packet in container.demux(video=0):
                try:
                    frames = packet.decode()
                except av.InvalidDataError:
                    continue
                if frames:
                    return frames[0].width, frames[0].height
        raise AssertionError("No valid relayed video frame was decoded")

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            time.sleep(1)
            sender = subprocess.Popen(
                (
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-re",
                    "-i",
                    "testsrc=size=160x120:rate=5",
                    "-frames:v",
                    "30",
                    "-c:v",
                    "libx264",
                    "-tune",
                    "zerolatency",
                    "-g",
                    "5",
                    "-pix_fmt",
                    "yuv420p",
                    "-payload_type",
                    "96",
                    "-f",
                    "rtp",
                    "-srtp_out_suite",
                    SRTP_SUITE,
                    "-srtp_out_params",
                    key,
                    f"srtp://127.0.0.1:{source_port}",
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # The relay must keep receiving without a camera reader attached.
            time.sleep(1.5)
            assert relay.poll() is None
            decoded = pool.submit(read_frame)
            try:
                dimensions = decoded.result(timeout=5)
            except FutureTimeoutError:
                relay.kill()
                relay.wait(timeout=2)
                assert relay.stderr
                raise AssertionError(
                    relay.stderr.read().decode(errors="replace")
                ) from None
            assert dimensions == (160, 120)
            sender.wait(timeout=10)
            assert sender.returncode == 0
    finally:
        if "sender" in locals() and sender.poll() is None:
            sender.kill()
            sender.wait(timeout=2)
        if relay.poll() is None:
            relay.kill()
            relay.wait(timeout=2)
