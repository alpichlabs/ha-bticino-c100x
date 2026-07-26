"""Azure B2C authentication used by the C100X mobile application."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import (
    B2C_BASE,
    B2C_CLIENT_ID,
    B2C_POLICY,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    B2C_TENANT,
    B2C_USER_AGENT,
)

TOKEN_REFRESH_BUFFER = 300


class AuthenticationError(Exception):
    """Authentication failed without retaining sensitive response bodies."""


class C100XAuth:
    """Authenticate and refresh a C100X Legrand account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        save_tokens: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._save_tokens = save_tokens
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def restore(self, data: dict[str, Any]) -> None:
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        self._expires_at = float(data.get("expires_at", 0))

    async def access_token(self) -> str:
        if self._valid:
            return self._access_token  # type: ignore[return-value]
        async with self._lock:
            if self._valid:
                return self._access_token  # type: ignore[return-value]
            if self._refresh_token:
                try:
                    await self._refresh()
                except AuthenticationError:
                    self._refresh_token = None
            if not self._valid:
                await self.authenticate()
        if not self._access_token:
            raise AuthenticationError("No access token returned")
        return self._access_token

    @property
    def _valid(self) -> bool:
        return bool(self._access_token and time.time() < self._expires_at - TOKEN_REFRESH_BUFFER)

    async def authenticate(self) -> None:
        verifier = secrets.token_urlsafe(48)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        cookie_fd, cookie_path = tempfile.mkstemp(prefix="bticino-c100x-", suffix=".cookies")
        os.close(cookie_fd)
        try:
            code = await self._authenticate_with_curl(challenge, cookie_path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(cookie_path)
        await self._exchange(
            {
                "grant_type": "authorization_code",
                "client_id": B2C_CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": B2C_REDIRECT_URI,
                "scope": B2C_SCOPE,
            }
        )

    async def _authenticate_with_curl(self, challenge: str, cookie_path: str) -> str:
        authorize_url = f"{B2C_BASE}/{B2C_TENANT}/oauth2/v2.0/authorize"
        params = {
            "p": B2C_POLICY,
            "client_id": B2C_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": B2C_REDIRECT_URI,
            "response_mode": "query",
            "scope": B2C_SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        html = await self._curl(
            "-L",
            "-b",
            cookie_path,
            "-c",
            cookie_path,
            f"{authorize_url}?{urlencode(params)}",
        )
        csrf = self._extract(html, r'"csrf":"([^"\\]+)"', "csrf")
        transaction = self._extract(html, r'"transId":"([^"\\]+)"', "transaction")
        tenant = self._extract(
            html,
            r'"hosts"\s*:\s*\{\s*"tenant"\s*:\s*"([^"\\]+)"',
            "tenant",
        )

        login_url = f"{B2C_BASE}{tenant}/SelfAsserted"
        login_data = urlencode(
            {
                "request_type": "RESPONSE",
                "logonIdentifier": self._username,
                "password": self._password,
            }
        )
        login_response = await self._curl(
            "-X",
            "POST",
            "-H",
            f"X-CSRF-TOKEN: {csrf}",
            "-H",
            "X-Requested-With: XMLHttpRequest",
            "-H",
            "Content-Type: application/x-www-form-urlencoded",
            "-b",
            cookie_path,
            "-c",
            cookie_path,
            "--data-binary",
            "@-",
            f"{login_url}?{urlencode({'tx': transaction, 'p': B2C_POLICY})}",
            stdin=login_data,
        )
        try:
            result = json.loads(login_response)
        except json.JSONDecodeError as err:
            raise AuthenticationError("Authentication service returned an invalid response") from err
        if str(result.get("status")) != "200":
            raise AuthenticationError("Invalid username or password")

        confirm_url = f"{B2C_BASE}{tenant}/api/CombinedSigninAndSignup/confirmed"
        confirm_params = urlencode(
            {"csrf_token": csrf, "tx": transaction, "p": B2C_POLICY}
        )
        headers = await self._curl(
            "-D",
            "-",
            "-o",
            "/dev/null",
            "--max-redirs",
            "0",
            "-b",
            cookie_path,
            "-c",
            cookie_path,
            f"{confirm_url}?{confirm_params}",
            allow_failure=True,
        )
        location = ""
        for line in headers.splitlines():
            if line.lower().startswith("location:"):
                location = line.split(":", 1)[1].strip()
                break
        query = parse_qs(urlparse(location).query)
        code = query.get("code", [None])[0]
        if not code:
            raise AuthenticationError("Authorization code was not returned")
        return code

    async def _curl(
        self,
        *arguments: str,
        stdin: str | None = None,
        allow_failure: bool = False,
    ) -> str:
        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["curl", "-sS", "-A", B2C_USER_AGENT, *arguments],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        try:
            result = await asyncio.to_thread(run)
        except (OSError, subprocess.SubprocessError) as err:
            raise AuthenticationError("Authentication transport failed") from err
        if result.returncode != 0 and not allow_failure:
            raise AuthenticationError("Authentication transport failed")
        return result.stdout

    async def _refresh(self) -> None:
        await self._exchange(
            {
                "grant_type": "refresh_token",
                "client_id": B2C_CLIENT_ID,
                "refresh_token": self._refresh_token,
                "redirect_uri": B2C_REDIRECT_URI,
                "scope": B2C_SCOPE,
            }
        )

    async def _exchange(self, data: dict[str, Any]) -> None:
        token_url = f"{B2C_BASE}/{B2C_TENANT}/oauth2/v2.0/token"
        async with self._session.post(token_url, params={"p": B2C_POLICY}, data=data) as response:
            payload = await response.json(content_type=None)
        if response.status >= 400 or "access_token" not in payload:
            raise AuthenticationError("Token exchange failed")
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))
        if self._save_tokens:
            await self._save_tokens(
                {
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "expires_at": self._expires_at,
                }
            )

    @staticmethod
    def _extract(value: str, pattern: str, label: str) -> str:
        match = re.search(pattern, value)
        if not match:
            raise AuthenticationError(f"Authentication page did not contain {label}")
        return match.group(1)

    async def user_oid(self) -> str:
        token = await self.access_token()
        try:
            encoded = token.split(".")[1]
            encoded += "=" * (-len(encoded) % 4)
            claims = json.loads(base64.urlsafe_b64decode(encoded))
            return str(claims.get("oid") or claims["sub"])
        except (IndexError, KeyError, ValueError, json.JSONDecodeError) as err:
            raise AuthenticationError("Access token does not contain a user identifier") from err
