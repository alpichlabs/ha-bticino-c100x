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
def test_ffmpeg_h264_fifo_is_decoded_by_pyav(tmp_path, socket_enabled) -> None:
    """Prove the exact FFmpeg-to-PyAV bounded local channel used by HA."""
    ffmpeg = shutil.which("ffmpeg")
    for port in range(52000, 62000, 2):
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
    fifo = tmp_path / "session.h264"
    os.mkfifo(fifo, 0o600)
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
            str(sdp),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-f",
            "h264",
            "-y",
            str(fifo),
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    def read_frame() -> tuple[int, int]:
        with av.open(
            str(fifo),
            format="h264",
            options={"analyzeduration": "0", "probesize": "32"},
        ) as container:
            frame = next(container.decode(video=0))
            return frame.width, frame.height

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            decoded = pool.submit(read_frame)
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
            try:
                dimensions = decoded.result(timeout=5)
            except FutureTimeoutError:
                receiver.kill()
                receiver.wait(timeout=2)
                assert receiver.stderr
                raise AssertionError(
                    receiver.stderr.read().decode(errors="replace")
                ) from None
            assert dimensions == (160, 120)
    finally:
        if receiver.poll() is None:
            receiver.kill()
            receiver.wait(timeout=2)
