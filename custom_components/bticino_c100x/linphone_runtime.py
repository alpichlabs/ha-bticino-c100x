"""Supervised IPC client for the GPL Linphone media runtime."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import platform
import tarfile
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import aiohttp

RUNTIME_PROTOCOL = 1
RUNTIME_VERSION = "0.1.0"
RUNTIME_ASSET = "bticino-c100x-linphone-0.1.0-linux-amd64.tar.gz"
RUNTIME_SHA256 = "586b9b79643c49e9a0cc19dfe2bf92693c264941168af28246524a5079bc514b"
RUNTIME_URL = (
    "https://github.com/alpichlabs/ha-bticino-c100x/releases/download/"
    f"runtime-v{RUNTIME_VERSION}/{RUNTIME_ASSET}"
)


class LinphoneRuntimeError(Exception):
    """The native runtime is unavailable or rejected a command."""


@dataclass(frozen=True, slots=True)
class MonitoringRequest:
    """Vendor-confirmed parameters for an outgoing entrance session."""

    target: str
    device_address: str
    video_direction: str = "recv_only"
    audio_direction: str = "send_recv"
    media_encryption: str = "srtp"
    media_encryption_mandatory: bool = True
    microphone_enabled: bool = False
    setup_timeout: int = 15
    no_media_timeout: int = 10

    @classmethod
    def for_external_unit(cls, device_address: str) -> MonitoringRequest:
        return cls(target="c100x", device_address=device_address)


def runtime_supported(machine: str | None = None) -> bool:
    """Return whether this release has a native runtime for the host."""
    return (machine or platform.machine()).casefold() in {"amd64", "x86_64"}


def verify_runtime(data: bytes, expected_sha256: str) -> None:
    """Verify a release artifact before it is installed."""
    if not expected_sha256:
        raise LinphoneRuntimeError("Linphone runtime checksum is not published")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256.casefold():
        raise LinphoneRuntimeError("Linphone runtime checksum mismatch")


class LinphoneRuntime:
    """Own one native helper process and its NDJSON control channel."""

    def __init__(
        self,
        executable: Path,
        socket_path: Path,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.executable = executable
        self.socket_path = socket_path
        self.on_event = on_event
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._sequence = 0

    async def start(self) -> None:
        if not runtime_supported():
            raise LinphoneRuntimeError(f"Unsupported Linphone runtime architecture: {platform.machine()}")
        self.socket_path.unlink(missing_ok=True)
        self.process = await asyncio.create_subprocess_exec(
            str(self.executable),
            "--socket",
            str(self.socket_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        for _ in range(100):
            if self.process.returncode is not None:
                raise LinphoneRuntimeError("Linphone runtime exited during startup")
            try:
                self.reader, self.writer = await asyncio.open_unix_connection(self.socket_path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                await asyncio.sleep(0.05)
        else:
            await self.close()
            raise LinphoneRuntimeError("Linphone runtime did not create its control socket")
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        hello = await self.command("hello")
        if hello.get("protocol") != RUNTIME_PROTOCOL:
            await self.close()
            raise LinphoneRuntimeError("Linphone runtime protocol mismatch")

    async def command(self, command: str, **payload: Any) -> dict[str, Any]:
        if not self.writer:
            raise LinphoneRuntimeError("Linphone runtime is not connected")
        self._sequence += 1
        request_id = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = {"id": request_id, "command": command, **payload}
        self.writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await self.writer.drain()
        try:
            response = await asyncio.wait_for(future, timeout=20)
        finally:
            self._pending.pop(request_id, None)
        if error := response.get("error"):
            raise LinphoneRuntimeError(str(error))
        return response

    async def register(
        self,
        *,
        sip_uri: str,
        username: str,
        password: str,
        domain: str,
        proxy: str,
        certificate_path: Path,
        private_key_path: Path,
        ca_path: Path,
        microphone_path: Path,
    ) -> None:
        await self.command(
            "register",
            sip_uri=sip_uri,
            username=username,
            password=password,
            domain=domain,
            proxy=proxy,
            certificate_path=str(certificate_path),
            private_key_path=str(private_key_path),
            ca_path=str(ca_path),
            microphone_path=str(microphone_path),
            expires=5_184_000,
        )

    async def start_monitoring(
        self,
        device_address: str,
        domain: str,
        media_path: Path | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        request = MonitoringRequest.for_external_unit(device_address)
        await self.command(
            "start_monitoring",
            **asdict(request),
            domain=domain,
            media_path=str(media_path) if media_path else None,
            snapshot_path=str(snapshot_path) if snapshot_path else None,
        )

    async def set_microphone(self, enabled: bool) -> None:
        await self.command("set_microphone", enabled=enabled)

    async def end_session(self) -> None:
        await self.command("end_session")

    async def snapshot(self) -> None:
        await self.command("snapshot")

    async def send_strike(self, recipient: str, payload: str) -> None:
        await self.command("send_strike", recipient=recipient, payload=payload)

    async def send_microphone_frame(self, pcm: bytes) -> None:
        await self.command("microphone_frame", pcm=base64.b64encode(pcm).decode())

    async def close(self) -> None:
        if self.writer:
            with contextlib.suppress(LinphoneRuntimeError, TimeoutError, ConnectionError):
                await self.command("shutdown")
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
        if self._reader_task:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            self._reader_task = None
        if self._stderr_task:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
        self.socket_path.unlink(missing_ok=True)

    async def _read_loop(self) -> None:
        assert self.reader
        while line := await self.reader.readline():
            message = json.loads(line)
            if request_id := message.get("id"):
                if (future := self._pending.get(int(request_id))) and not future.done():
                    future.set_result(message)
                continue
            await self.on_event(message)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(LinphoneRuntimeError("Linphone runtime disconnected"))

    async def _drain_stderr(self) -> None:
        """Prevent native logging from blocking while never exposing its contents."""
        assert self.process and self.process.stderr
        while await self.process.stderr.readline():
            pass


async def download_runtime(session: aiohttp.ClientSession, destination: Path) -> Path:
    """Download and atomically install the pinned runtime asset."""
    if not runtime_supported():
        raise LinphoneRuntimeError(f"Unsupported Linphone runtime architecture: {platform.machine()}")
    async with session.get(RUNTIME_URL) as response:
        if response.status != 200:
            raise LinphoneRuntimeError(f"Linphone runtime download failed with status {response.status}")
        data = await response.read()
    verify_runtime(data, RUNTIME_SHA256)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = destination / "runtime.tmp.tar.gz"
    await asyncio.to_thread(archive.write_bytes, data)

    def extract() -> None:
        with tarfile.open(archive, "r:gz") as package:
            members = package.getmembers()
            if any(member.name.startswith(("/", "../")) or "/../" in member.name for member in members):
                raise LinphoneRuntimeError("Linphone runtime archive contains an unsafe path")
            package.extractall(destination, members=members, filter="data")
        archive.unlink()

    await asyncio.to_thread(extract)
    executable = destination / "bin" / "bticino-c100x-linphone"
    if not executable.is_file():
        raise LinphoneRuntimeError("Linphone runtime archive has no executable")
    os.chmod(executable, 0o700)
    return executable
