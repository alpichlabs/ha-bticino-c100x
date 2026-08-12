"""Minimal asynchronous SIP-over-TLS client for BTicino Door Entry."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import secrets
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any

from .const import (
    SIP_PORT,
    SIP_REGISTER_EXPIRES,
    SIP_REREGISTER_SECONDS,
    SIP_SERVER,
    SIP_USER_AGENT,
)
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


@dataclass(slots=True)
class SipDialog:
    """Established outgoing SIP dialog."""

    call_id: str
    local_uri: str
    remote_uri: str
    local_tag: str
    remote_to: str
    remote_target: str
    route_set: tuple[str, ...]
    local_sequence: int


def _split_header_values(value: str) -> list[str]:
    """Split comma-separated SIP route values outside angle brackets."""
    values: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character == "<":
            depth += 1
        elif character == ">":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            values.append(value[start:index].strip())
            start = index + 1
    if tail := value[start:].strip():
        values.append(tail)
    return values


def _first_uri(value: str) -> str | None:
    """Extract the first SIP URI from a name-address header."""
    if "<" in value and ">" in value:
        return value.split("<", 1)[1].split(">", 1)[0]
    clean = value.split(";", 1)[0].strip()
    return clean or None


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
                    key = name.lower().strip()
                    clean_value = value.strip()
                    if key == "record-route" and key in headers:
                        headers[key] = f"{headers[key]}, {clean_value}"
                    else:
                        headers[key] = clean_value
            length = int(headers.get("content-length", "0"))
            total = header_end + 4 + length
            if len(self._buffer) < total:
                break
            body = bytes(self._buffer[header_end + 4 : total])
            del self._buffer[:total]
            messages.append(SipMessage(lines[0], headers, body))
        return messages


def _create_ssl_context(
    certificate_path: str, private_key_path: str, ca_path: str
) -> ssl.SSLContext:
    """Create the SIP TLS context outside Home Assistant's event loop."""
    context = ssl.create_default_context(cafile=ca_path)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
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
        ca_path: str,
        on_ring: Callable[[dict[str, Any]], Awaitable[None]],
        on_call_end: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.account = account
        self._certificate_path = certificate_path
        self._private_key_path = private_key_path
        self._ca_path = ca_path
        self._on_ring = on_ring
        self.on_call_end = on_call_end
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._registration_task: asyncio.Task | None = None
        self._pending: dict[tuple[str, str], asyncio.Future[SipMessage]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._send_lock = asyncio.Lock()
        self._last_transaction: dict[str, Any] | None = None
        self._dialog: SipDialog | None = None
        self.registered = False

    async def connect(self) -> None:
        context = await asyncio.to_thread(
            _create_ssl_context,
            self._certificate_path,
            self._private_key_path,
            self._ca_path,
        )
        self._reader, self._writer = await asyncio.open_connection(
            SIP_SERVER, SIP_PORT, ssl=context, server_hostname=SIP_SERVER
        )
        self._read_task = asyncio.create_task(self._read_loop())
        await self.register()
        self._registration_task = asyncio.create_task(self._refresh_registration())

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.end_monitoring()
        self.registered = False
        if self._registration_task:
            self._registration_task.cancel()
            await asyncio.gather(self._registration_task, return_exceptions=True)
            self._registration_task = None
        if self._read_task:
            self._read_task.cancel()
            await asyncio.gather(self._read_task, return_exceptions=True)
            self._read_task = None
        if self._writer:
            self._writer.close()
            # TLS peers can close first or abort the shutdown handshake. The
            # connection is already unusable at this point, so teardown must
            # not prevent Home Assistant from unloading/reloading the entry.
            with contextlib.suppress(OSError, ssl.SSLError):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None
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
        tasks = {task for task in (self._read_task, self._registration_task) if task}
        if not tasks:
            return
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        await next(iter(done))

    async def register(self) -> None:
        uri = f"sip:{self.account.domain}"
        response = await self._authenticated_request("REGISTER", uri, b"", register=True)
        if response.status_code != 200:
            raise SipError(f"SIP registration failed with status {response.status_code}")
        self.registered = True

    async def _refresh_registration(self) -> None:
        while True:
            await asyncio.sleep(SIP_REREGISTER_SECONDS)
            await self.register()

    async def release_door(self, lock_id: str, gateway_id: str) -> None:
        """Release a Classe 100X strike using its topology module ID."""
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": str(secrets.randbelow(2**31)),
                "method": "lock.setStatus",
                "params": [
                    {
                        "status": "open",
                        "receiver": {"plant": {"coal": {"id": lock_id}}},
                    }
                ],
            },
            separators=(",", ":"),
        ).encode()
        gateway_domain = (
            gateway_id
            if gateway_id.endswith(".bs.iotleg.com")
            else f"{gateway_id}.bs.iotleg.com"
        )
        uri = f"sip:c100x@{gateway_domain}"
        response = await self._authenticated_request("MESSAGE", uri, body)
        if response.status_code != 200:
            raise SipError(f"Door release failed with SIP status {response.status_code}")

    async def activate_staircase(
        self, module_id: str, gateway_id: str
    ) -> None:
        """Activate a Classe 100X staircase actuator."""
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": str(secrets.randbelow(2**31)),
                "method": "light.setStatus",
                "params": [
                    {
                        "status": "on",
                        "receiver": {"plant": {"coal": {"id": module_id}}},
                    }
                ],
            },
            separators=(",", ":"),
        ).encode()
        gateway_domain = (
            gateway_id
            if gateway_id.endswith(".bs.iotleg.com")
            else f"{gateway_id}.bs.iotleg.com"
        )
        uri = f"sip:c100x@{gateway_domain}"
        response = await self._authenticated_request("MESSAGE", uri, body)
        if response.status_code != 200:
            raise SipError(
                f"Staircase activation failed with SIP status {response.status_code}"
            )

    async def start_monitoring(self, offer_sdp: str) -> bytes:
        """Start one user-initiated monitoring dialog and return its SDP answer."""
        if self._dialog is not None:
            raise SipError("A monitoring dialog is already active")
        uri = f"sip:c100x@{self.account.domain}"
        response = await self._authenticated_request(
            "INVITE",
            uri,
            offer_sdp.encode(),
            content_type="application/sdp",
            extra_headers=("Accept: application/sdp",),
        )
        transaction = self._last_transaction or {}
        if response.status_code != 200:
            raise SipError(f"Monitoring call failed with SIP status {response.status_code}")
        if "application/sdp" not in response.headers.get("content-type", "").casefold():
            raise SipError("Monitoring call returned no SDP answer")
        remote_to = response.headers.get("to", "")
        if ";tag=" not in remote_to.casefold():
            raise SipError("Monitoring call returned no remote dialog tag")
        contact = _first_uri(response.headers.get("contact", "")) or uri
        routes = tuple(reversed(_split_header_values(response.headers.get("record-route", ""))))
        try:
            dialog = SipDialog(
                call_id=str(transaction["call_id"]),
                local_uri=f"sip:{self.account.username}@{self.account.domain}",
                remote_uri=uri,
                local_tag=str(transaction["tag"]),
                remote_to=remote_to,
                remote_target=contact,
                route_set=routes,
                local_sequence=int(transaction["sequence"]),
            )
        except KeyError as err:
            raise SipError("Monitoring transaction state was incomplete") from err
        self._dialog = dialog
        await self._send_ack(dialog)
        return response.body

    async def end_monitoring(self) -> None:
        """Terminate the active monitoring dialog, if any."""
        dialog, self._dialog = self._dialog, None
        if dialog is None or self._writer is None:
            return
        dialog.local_sequence += 1
        response = await self._dialog_request(dialog, "BYE", dialog.local_sequence)
        if response.status_code not in {200, 481}:
            raise SipError(f"Monitoring teardown failed with SIP status {response.status_code}")

    async def _send_ack(self, dialog: SipDialog) -> None:
        await self._dialog_request(dialog, "ACK", dialog.local_sequence, wait=False)

    async def _dialog_request(
        self, dialog: SipDialog, method: str, sequence: int, *, wait: bool = True
    ) -> SipMessage:
        branch = f"z9hG4bK.{secrets.token_hex(8)}"
        local = "127.0.0.1:5060"
        headers = [
            f"Via: SIP/2.0/TLS {local};branch={branch};rport",
            f"From: <{dialog.local_uri}>;tag={dialog.local_tag}",
            f"To: {dialog.remote_to}",
            f"Call-ID: {dialog.call_id}",
            f"CSeq: {sequence} {method}",
            "Max-Forwards: 70",
            f"User-Agent: {SIP_USER_AGENT}",
            f"Contact: <sip:{self.account.username}@{self.account.domain};transport=tls>",
        ]
        headers.extend(f"Route: {route}" for route in dialog.route_set)
        headers.append("Content-Length: 0")
        raw = (
            f"{method} {dialog.remote_target} SIP/2.0\r\n"
            + "\r\n".join(headers)
            + "\r\n\r\n"
        )
        if not self._writer:
            raise SipError("SIP connection is not open")
        if not wait:
            self._writer.write(raw.encode())
            await self._writer.drain()
            return SipMessage("SIP/2.0 200 Local ACK", {})
        cseq = f"{sequence} {method}"
        future = asyncio.get_running_loop().create_future()
        self._pending[(dialog.call_id, cseq)] = future
        self._writer.write(raw.encode())
        await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=20)
        finally:
            self._pending.pop((dialog.call_id, cseq), None)

    async def _authenticated_request(
        self,
        method: str,
        uri: str,
        body: bytes,
        register: bool = False,
        *,
        content_type: str = "text/plain",
        extra_headers: tuple[str, ...] = (),
    ) -> SipMessage:
        async with self._send_lock:
            transaction: dict[str, Any] = {}
            first = await self._request(
                method,
                uri,
                body,
                register=register,
                transaction=transaction,
                content_type=content_type,
                extra_headers=extra_headers,
            )
            if method == "INVITE" and first.status_code and first.status_code >= 300:
                await self._send_failure_ack(uri, transaction, first)
            if first.status_code not in (401, 407):
                self._last_transaction = transaction
                return first
            header_name = "www-authenticate" if first.status_code == 401 else "proxy-authenticate"
            challenge_value = first.headers.get(header_name)
            if not challenge_value:
                raise SipError("SIP authentication challenge was incomplete")
            challenge = parse_digest_challenge(challenge_value)
            authorization = digest_authorization(account=self.account, method=method, uri=uri, challenge=challenge)
            response = await self._request(
                method,
                uri,
                body,
                register=register,
                transaction=transaction,
                content_type=content_type,
                extra_headers=extra_headers,
                authorization=("Authorization" if first.status_code == 401 else "Proxy-Authorization", authorization),
            )
            if method == "INVITE" and response.status_code and response.status_code >= 300:
                await self._send_failure_ack(uri, transaction, response)
            self._last_transaction = transaction
            return response

    async def _send_failure_ack(
        self, uri: str, transaction: dict[str, Any], response: SipMessage
    ) -> None:
        """Acknowledge a non-2xx INVITE final response before retry/teardown."""
        sequence = int(transaction["sequence"])
        branch = str(transaction["branch"])
        headers = [
            f"Via: SIP/2.0/TLS 127.0.0.1:5060;branch={branch};rport",
            f"From: {transaction['from']}",
            f"To: {response.headers.get('to', f'<{uri}>')}",
            f"Call-ID: {transaction['call_id']}",
            f"CSeq: {sequence} ACK",
            "Max-Forwards: 70",
            f"Route: <sip:{SIP_SERVER};transport=tls;lr>",
            f"User-Agent: {SIP_USER_AGENT}",
            "Content-Length: 0",
        ]
        if not self._writer:
            raise SipError("SIP connection is not open")
        self._writer.write(
            (f"ACK {uri} SIP/2.0\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode()
        )
        await self._writer.drain()

    async def _request(
        self,
        method: str,
        uri: str,
        body: bytes,
        *,
        register: bool,
        transaction: dict[str, Any] | None = None,
        content_type: str = "text/plain",
        extra_headers: tuple[str, ...] = (),
        authorization: tuple[str, str] | None = None,
    ) -> SipMessage:
        transaction = transaction if transaction is not None else {}
        call_id = transaction.setdefault("call_id", secrets.token_hex(12))
        sequence = int(transaction.setdefault("sequence", secrets.randbelow(9999) + 1))
        if authorization:
            sequence += 1
            transaction["sequence"] = sequence
        cseq = f"{sequence} {method}"
        branch = f"z9hG4bK.{secrets.token_hex(8)}"
        transaction["branch"] = branch
        tag = transaction.setdefault("tag", secrets.token_hex(8))
        local = "127.0.0.1:5060"
        from_uri = f"<sip:{self.account.username}@{self.account.domain}>;tag={tag}"
        transaction["from"] = from_uri
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
            headers.extend(
                [
                    f"Contact: <sip:{self.account.username}@{self.account.domain};transport=tls>",
                    f"Route: <sip:{SIP_SERVER};transport=tls;lr>",
                    f"Content-Type: {content_type}",
                ]
            )
        headers.extend(extra_headers)
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
            # The official Classe 100X app declines calls whose remote SIP URI
            # does not contain c100x@<selected-gateway-domain>.
            expected_gateway = f"c100x@{self.account.domain}".casefold()
            if expected_gateway not in message.headers.get("from", "").casefold():
                await self._respond(message, 486, "Busy Here")
                return
            await self._on_ring(
                {
                    "call_id": message.headers.get("call-id", ""),
                }
            )
            await self._respond(message, 180, "Ringing")
            task = asyncio.create_task(self._delayed_busy(message))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        elif message.method == "BYE":
            await self._respond(message, 200, "OK")
            if self._dialog and message.headers.get("call-id") == self._dialog.call_id:
                self._dialog = None
                if self.on_call_end:
                    await self.on_call_end()
        elif message.method in ("CANCEL", "OPTIONS", "MESSAGE"):
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
