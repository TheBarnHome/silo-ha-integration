"""Small asynchronous client for the Silo v2 API.

The client only speaks HTTP: no Home Assistant imports, so it can be unit
tested on its own. Every call goes through ``_request`` which classifies the
server's RFC 9457 problem documents into typed exceptions.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from typing import Any, Final

import aiohttp

from .const import (
    API_PREFIX,
    COMMAND_DEADLINE_MS,
    COMMAND_REASON,
    DEFAULT_TIMEOUT,
    LATEST_SEQUENCE_HEADER,
)

# Guard against a pagination loop that never ends.
MAX_PAGES: Final = 50


class SiloError(Exception):
    """Base class for every Silo API error."""


class SiloConnectionError(SiloError):
    """The server could not be reached."""


class SiloAuthError(SiloError):
    """The API key was refused (401)."""


class SiloPermissionError(SiloError):
    """The credential is valid but lacks authority (403)."""


class SiloNotFoundError(SiloError):
    """The requested resource does not exist (404)."""


class SiloConflictError(SiloError):
    """The server refused a sequenced command (409)."""

    def __init__(self, message: str, *, latest_sequence: int | None = None) -> None:
        """Initialize the conflict with the server's latest applied sequence."""
        super().__init__(message)
        self.latest_sequence = latest_sequence


class SiloRateLimitError(SiloError):
    """A rate-limit budget is exhausted (429)."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        """Initialize the rate-limit error with the advertised retry delay."""
        super().__init__(message)
        self.retry_after = retry_after


class SiloServerError(SiloError):
    """The server failed the request (5xx)."""


class SiloUnsupportedApiError(SiloError):
    """The server does not serve the native API major this integration speaks."""


def _problem_message(status: int, body: Any) -> str:
    """Build a readable message out of an RFC 9457 problem document."""
    if isinstance(body, Mapping):
        for key in ("detail", "title"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        kind = body.get("type")
        if isinstance(kind, str) and kind:
            return f"{kind} (HTTP {status})"
    return f"HTTP {status}"


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header carrying seconds."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class SiloClient:
    """Talk to one Silo server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client for a normalized server URL."""
        self._session = session
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        # Last sequence allocated per playback session, so a command is never
        # refused as stale because Home Assistant restarted.
        self._sequences: dict[str, int] = {}

    @property
    def url(self) -> str:
        """Return the normalized server URL."""
        return self._url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        """Perform one request and return the decoded JSON body."""
        url = f"{self._url}{API_PREFIX}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    method, url, params=params, json=payload, headers=headers
                ) as response:
                    text = await response.text()
                    status = response.status
                    latest_raw = response.headers.get(LATEST_SEQUENCE_HEADER)
                    retry_raw = response.headers.get("Retry-After")
        except TimeoutError as err:
            raise SiloConnectionError(f"Timeout talking to {self._url}") from err
        except (aiohttp.ClientError, OSError) as err:
            raise SiloConnectionError(f"Cannot talk to {self._url}: {err}") from err

        body: Any = None
        if text:
            try:
                body = json.loads(text)
            except ValueError:
                body = text

        if 200 <= status < 300:
            return body

        message = _problem_message(status, body)
        if status == 401:
            raise SiloAuthError(message)
        if status == 403:
            raise SiloPermissionError(message)
        if status == 404:
            raise SiloNotFoundError(message)
        if status == 409:
            latest = None
            if latest_raw is not None:
                try:
                    latest = int(latest_raw)
                except ValueError:
                    latest = None
            raise SiloConflictError(message, latest_sequence=latest)
        if status == 429:
            raise SiloRateLimitError(message, retry_after=_parse_retry_after(retry_raw))
        if status >= 500:
            raise SiloServerError(message)
        raise SiloError(message)

    async def async_system_info(self) -> dict[str, Any]:
        """Read the public server identity."""
        body = await self._request("GET", "/system/info")
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected system info payload")
        return dict(body)

    async def async_check_api(self) -> dict[str, Any]:
        """Read the server identity and refuse an unexpected API major."""
        info = await self.async_system_info()
        major = info.get("api_major")
        if major != 2:
            raise SiloUnsupportedApiError(
                f"Silo serves native API major {major!r}, this integration needs 2"
            )
        return info

    async def async_playback_capabilities(self) -> dict[str, Any]:
        """Read the playback capability document (carries the installation id)."""
        body = await self._request("GET", "/playback/capabilities")
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected playback capability payload")
        return dict(body)

    async def async_session_capabilities(self) -> dict[str, Any]:
        """Read the administrator session capability document."""
        body = await self._request("GET", "/admin/sessions/capabilities")
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected session capability payload")
        return dict(body)

    async def async_command_capabilities(self) -> dict[str, Any]:
        """Read which administrator playback actions this server dispatches."""
        body = await self._request("GET", "/admin/sessions/command-capabilities")
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected command capability payload")
        return dict(body)

    async def async_sessions(self) -> list[dict[str, Any]]:
        """Read every live playback session, following the opaque cursor."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            body = await self._request("GET", "/admin/sessions", params=params)
            if not isinstance(body, Mapping):
                raise SiloError("Unexpected session collection payload")
            page_items = body.get("items") or []
            if not isinstance(page_items, list):
                raise SiloError("Unexpected session collection items")
            items.extend(item for item in page_items if isinstance(item, dict))
            page = body.get("page")
            if not isinstance(page, Mapping) or not page.get("has_more"):
                return items
            next_cursor = page.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return items
            cursor = next_cursor
        raise SiloError("Session pagination did not terminate")

    async def async_session_summary(self) -> dict[str, Any]:
        """Read the bounded live playback summary."""
        body = await self._request("GET", "/admin/sessions/summary")
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected session summary payload")
        return dict(body)

    async def async_stats(self, *, refresh: bool = False) -> dict[str, Any]:
        """Read the dashboard statistics used by the sensors."""
        params = {"refresh": "true"} if refresh else None
        body = await self._request("GET", "/admin/stats", params=params)
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected statistics payload")
        return dict(body)

    async def async_libraries(self) -> list[dict[str, Any]]:
        """Read the configured libraries."""
        body = await self._request("GET", "/libraries")
        if not isinstance(body, Mapping):
            raise SiloError("Unexpected library collection payload")
        items = body.get("items")
        if not isinstance(items, list):
            raise SiloError("Unexpected library collection items")
        return [item for item in items if isinstance(item, dict)]

    async def async_scan(
        self, library_id: str, path: str | None = None
    ) -> dict[str, Any]:
        """Ask the server to scan a library, a subtree or a single file."""
        payload: dict[str, Any] = {"library_id": library_id}
        if path:
            payload["path"] = path
        return await self._request("POST", "/scan", payload=payload) or {}

    def _next_sequence(self, session_id: str) -> int:
        """Allocate a sequence strictly above the last one used for a session."""
        sequence = max(int(time.time() * 1000), self._sequences.get(session_id, 0) + 1)
        self._sequences[session_id] = sequence
        return sequence

    def _note_sequence(self, session_id: str, sequence: int) -> None:
        """Remember the server's applied sequence for a session."""
        current = self._sequences.get(session_id, 0)
        if sequence > current:
            self._sequences[session_id] = sequence

    async def async_command(
        self,
        session_id: str,
        action: str,
        *,
        message: str | None = None,
        title: str | None = None,
        reason: str | None = COMMAND_REASON,
        deadline_ms: int = COMMAND_DEADLINE_MS,
    ) -> dict[str, Any]:
        """Dispatch one sequenced administrator command on a live session.

        The command identity is allocated once and reused on the single retry a
        stale sequence allows, so the server applies the command at most once.
        """
        command_id = str(uuid.uuid4())
        sequence = self._next_sequence(session_id)
        payload: dict[str, Any] = {
            "command_id": command_id,
            "sequence": sequence,
            "deadline_ms": deadline_ms,
        }
        if reason:
            payload["reason"] = reason
        if message is not None:
            payload["message"] = message
            if title:
                payload["title"] = title

        path = f"/admin/sessions/{session_id}/{action}"
        try:
            body = await self._request("POST", path, payload=payload)
        except SiloConflictError as err:
            if err.latest_sequence is None:
                raise
            # The session holds a newer applied sequence (for example a command
            # issued before a Home Assistant restart): allocate above it once.
            sequence = err.latest_sequence + 1
            payload["sequence"] = sequence
            body = await self._request("POST", path, payload=payload)
        self._note_sequence(session_id, sequence)
        return body if isinstance(body, dict) else {}
