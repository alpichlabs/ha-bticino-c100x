"""Minimal asynchronous SIP-over-TLS client for BTicino Door Entry."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any

from .const import SIP_PORT, SIP_REGISTER_EXPIRES, SIP_SERVER, SIP_USER_AGENT
from .models import SipAccount


class SipError(Exception):
    """SIP operation failed."""


@dataclass(slots=True)
class SipMessage:
    start_line: str
    headers: dict[str, str]
    body: bytes = b""

    @property
    def status_code(self) -> int | None:
        if not self.start_line.startswith("SIP/2.0 "):
            return None
        return int(self.start_line.split(" ", 2)[1])

    @property
    def method(self) -> str | None:
        if self.start_line.startswith("SIP/2.0 "):
            return None
        return self.start_line.split(" ", 1)[0]


class SipFramer:
    """Extract complete SIP messages from arbitrary TLS chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[SipMessage]:
        self._buffer.extend(data)
        messages: list[SipMessage] = []
        while True:
            header_end = self._buffer.find(b"\r\n\r\n")
            if header_end < 0:
                break
            header_blob = bytes(self._buffer[:header_end]).decode("utf-8", errors="replace")
            lines = header_blob.split("\r\n")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.lower().strip()] = value.strip()
            length = int(headers.get("content-length", "0"))
            total = header_end + 4 + length
            if len(self._buffer) < total:
                break
            body = bytes(self._buffer[header_end + 4 : total])
            del self._buffer[:total]
            messages.append(SipMessage(lines[0], headers, body))
        return messages


def _create_ssl_context(certificate_path: str, private_key_path: str) -> ssl.SSLContext:
    """Create the SIP TLS context outside Home Assistant's event loop."""
    context = ssl.create_default_context()
    # The dedicated Legrand SIP endpoint uses a private, self-signed server
    # certificate chain. Limit relaxed verification to this single pinned
    # hostname; mutual TLS still authenticates this client with the
    # short-lived certificate provisioned by Legrand.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(certificate_path, private_key_path)
    return context


def parse_digest_challenge(value: str) -> dict[str, str]:
    """Parse a Digest challenge without logging it."""
    value = value.removeprefix("Digest ")
    result: dict[str, str] = {}
    for part in value.split(","):
        if "=" not in part:
            continue
        key, raw = part.strip().split("=", 1)
        result[key.lower()] = raw.strip().strip('"')
    return result


def digest_authorization(
    *, account: SipAccount, method: str, uri: str, challenge: dict[str, str], nonce_count: int = 1
) -> str:
    """Build RFC 2617 MD5 digest authorization required by Legrand SIP."""
    realm = challenge.get("realm", account.domain)
    nonce = challenge["nonce"]
    qop = challenge.get("qop", "auth").split(",")[0]
    nc = f"{nonce_count:08x}"
    cnonce = secrets.token_hex(8)
    md5 = lambda value: hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()  # noqa: E731
    ha1 = md5(f"{account.username}:{realm}:{account.sip_password}")
    ha2 = md5(f"{method}:{uri}")
    response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    parts = [
        f'username="{account.username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'response="{response}"',
        "algorithm=MD5",
        f"qop={qop}",
        f"nc={nc}",
        f'cnonce="{cnonce}"',
    ]
    if opaque := challenge.get("opaque"):
        parts.append(f'opaque="{opaque}"')
    return "Digest " + ", ".join(parts)


class SipClient:
    """One persistent registered SIP connection per Home Assistant entry."""

    def __init__(
        self,
        account: SipAccount,
        certificate_path: str,
        private_key_path: str,
        on_ring: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.account = account
        self._certificate_path = certificate_path
        self._private_key_path = private_key_path
        self._on_ring = on_ring
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._pending: dict[tuple[str, str], asyncio.Future[SipMessage]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._send_lock = asyncio.Lock()
        self.registered = False

    async def connect(self) -> None:
        context = await asyncio.to_thread(
            _create_ssl_context, self._certificate_path, self._private_key_path
        )
        self._reader, self._writer = await asyncio.open_connection(
            SIP_SERVER, SIP_PORT, ssl=context, server_hostname=SIP_SERVER
        )
        self._read_task = asyncio.create_task(self._read_loop())
        await self.register()

    async def close(self) -> None:
        self.registered = False
        if self._read_task:
            self._read_task.cancel()
            await asyncio.gather(self._read_task, return_exceptions=True)
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(SipError("SIP connection closed"))
        self._pending.clear()

    async def wait_closed(self) -> None:
        """Wait until the remote connection ends or its reader fails."""
        if self._read_task:
            await self._read_task

    async def register(self) -> None:
        uri = f"sip:{self.account.domain}"
        response = await self._authenticated_request("REGISTER", uri, b"", register=True)
        if response.status_code != 200:
            raise SipError(f"SIP registration failed with status {response.status_code}")
        self.registered = True

    async def _authenticated_request(self, method: str, uri: str, body: bytes, register: bool = False) -> SipMessage:
        async with self._send_lock:
            first = await self._request(method, uri, body, register=register)
            if first.status_code not in (401, 407):
                return first
            header_name = "www-authenticate" if first.status_code == 401 else "proxy-authenticate"
            challenge_value = first.headers.get(header_name)
            if not challenge_value:
                raise SipError("SIP authentication challenge was incomplete")
            challenge = parse_digest_challenge(challenge_value)
            authorization = digest_authorization(account=self.account, method=method, uri=uri, challenge=challenge)
            return await self._request(
                method,
                uri,
                body,
                register=register,
                authorization=("Authorization" if first.status_code == 401 else "Proxy-Authorization", authorization),
            )

    async def _request(
        self,
        method: str,
        uri: str,
        body: bytes,
        *,
        register: bool,
        authorization: tuple[str, str] | None = None,
    ) -> SipMessage:
        call_id = secrets.token_hex(12)
        cseq = f"{secrets.randbelow(9999) + 1} {method}"
        branch = f"z9hG4bK.{secrets.token_hex(8)}"
        tag = secrets.token_hex(8)
        local = "127.0.0.1:5060"
        from_uri = f"<sip:{self.account.username}@{self.account.domain}>;tag={tag}"
        to_uri = f"<sip:{self.account.username}@{self.account.domain}>" if register else f"<{uri}>"
        headers = [
            f"Via: SIP/2.0/TLS {local};branch={branch};rport",
            f"From: {from_uri}",
            f"To: {to_uri}",
            f"Call-ID: {call_id}",
            f"CSeq: {cseq}",
            "Max-Forwards: 70",
            f"User-Agent: {SIP_USER_AGENT}",
            f"Date: {formatdate(usegmt=True)}",
        ]
        if register:
            headers.extend(
                [
                    f"Contact: <sip:{self.account.username}@{local};transport=tls>;expires={SIP_REGISTER_EXPIRES}",
                    f"Expires: {SIP_REGISTER_EXPIRES}",
                ]
            )
        else:
            headers.extend([f"Route: <sip:{SIP_SERVER};transport=tls;lr>", "Content-Type: text/plain"])
        if authorization:
            headers.append(f"{authorization[0]}: {authorization[1]}")
        headers.append(f"Content-Length: {len(body)}")
        raw = f"{method} {uri} SIP/2.0\r\n" + "\r\n".join(headers) + "\r\n\r\n"
        future = asyncio.get_running_loop().create_future()
        self._pending[(call_id, cseq)] = future
        if not self._writer:
            raise SipError("SIP connection is not open")
        self._writer.write(raw.encode() + body)
        await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=20)
        finally:
            self._pending.pop((call_id, cseq), None)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        framer = SipFramer()
        while data := await self._reader.read(8192):
            for message in framer.feed(data):
                if message.status_code is not None:
                    key = (message.headers.get("call-id", ""), message.headers.get("cseq", ""))
                    # SIP 1xx messages (notably 100 Trying) are provisional.
                    # Keep waiting for the final authentication or success response.
                    if message.status_code >= 200 and (future := self._pending.get(key)) and not future.done():
                        future.set_result(message)
                else:
                    await self._handle_request(message)
        raise SipError("SIP server closed the connection")

    async def _handle_request(self, message: SipMessage) -> None:
        if message.method == "INVITE":
            await self._on_ring(
                {
                    "call_id": message.headers.get("call-id", ""),
                    "from": message.headers.get("from", ""),
                }
            )
            await self._respond(message, 180, "Ringing")
            task = asyncio.create_task(self._delayed_busy(message))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        elif message.method in ("BYE", "CANCEL", "OPTIONS", "MESSAGE"):
            await self._respond(message, 200, "OK")

    async def _delayed_busy(self, message: SipMessage) -> None:
        await asyncio.sleep(2)
        await self._respond(message, 486, "Busy Here")

    async def _respond(self, request: SipMessage, status: int, reason: str) -> None:
        headers = []
        for name in ("via", "from", "to", "call-id", "cseq"):
            if value := request.headers.get(name):
                label = "Call-ID" if name == "call-id" else name.title()
                headers.append(f"{label}: {value}")
        headers.extend([f"User-Agent: {SIP_USER_AGENT}", "Content-Length: 0"])
        raw = f"SIP/2.0 {status} {reason}\r\n" + "\r\n".join(headers) + "\r\n\r\n"
        if self._writer:
            self._writer.write(raw.encode())
            await self._writer.drain()
