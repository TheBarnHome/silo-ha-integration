"""Fixtures for the Silo integration tests."""

from __future__ import annotations

import re
from typing import Any

import pytest
from custom_components.silo.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL, DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from . import data as data_defaults
from .const import INSTALLATION_ID, MOCK_API_KEY, MOCK_URL

pytest_plugins = ["pytest_homeassistant_custom_component"]

COMMAND_PATTERN = re.compile(
    rf"{re.escape(MOCK_URL)}/api/v2/admin/sessions/[^/]+"
    r"/(pause|resume|stop|message|terminate)"
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/silo in every test."""
    yield


class SiloMock:
    """Fake Silo server backed by aiohttp mocks."""

    def __init__(self, aioclient_mock) -> None:
        """Register every endpoint the integration reads."""
        self._mock = aioclient_mock
        self.base = f"{MOCK_URL}/api/v2"
        self.sessions: list[dict[str, Any]] = []
        self.actions: list[str] = list(data_defaults.DEFAULT_ACTIONS)
        self.stats: dict[str, Any] = data_defaults.stats_payload()
        self.command_calls: list[tuple[str, dict[str, Any]]] = []
        self.scan_calls: list[dict[str, Any]] = []
        # Latest sequence the server reports on a stale refusal, once.
        self.stale_latest: int | None = None
        self.command_status: int = 202
        self.scan_status: int = 202
        self.sessions_status: int = 200
        self.sessions_calls = 0
        self._install()

    def _install(self) -> None:
        from . import data

        self._mock.get(f"{self.base}/system/info", json=data.system_info_payload())
        self._mock.get(
            f"{self.base}/playback/capabilities",
            json=data.playback_capabilities_payload(),
        )
        self._mock.get(
            f"{self.base}/admin/sessions/capabilities",
            json=data.session_capabilities_payload(),
        )
        self._mock.get(
            f"{self.base}/admin/sessions/command-capabilities",
            side_effect=self._capabilities_response,
        )
        self._mock.get(
            f"{self.base}/admin/sessions", side_effect=self._sessions_response
        )
        self._mock.get(f"{self.base}/admin/stats", side_effect=self._stats_response)
        self._mock.post(COMMAND_PATTERN, side_effect=self._command_response)
        self._mock.post(f"{self.base}/scan", side_effect=self._scan_response)

    async def _capabilities_response(self, method, url, payload):
        from . import data as payloads

        return AiohttpClientMockResponse(
            method, url, json=payloads.command_capabilities_payload(self.actions)
        )

    async def _stats_response(self, method, url, payload):
        return AiohttpClientMockResponse(method, url, json=self.stats)

    async def _sessions_response(self, method, url, payload):
        from . import data as payloads

        self.sessions_calls += 1
        if self.sessions_status != 200:
            return AiohttpClientMockResponse(
                method,
                url,
                status=self.sessions_status,
                json={"type": "authentication_required", "detail": "no key"},
            )
        return AiohttpClientMockResponse(
            method, url, json=payloads.sessions_payload(self.sessions)
        )

    async def _command_response(self, method, url, payload):
        from . import data as payloads

        match = COMMAND_PATTERN.search(str(url))
        action = match.group(1) if match else "unknown"
        self.command_calls.append((action, dict(payload)))
        if self.stale_latest is not None:
            latest = self.stale_latest
            self.stale_latest = None
            return AiohttpClientMockResponse(
                method,
                url,
                status=409,
                json={
                    "type": "conflict",
                    "title": "Conflict",
                    "detail": (
                        "The command sequence is behind the session's "
                        "latest applied command."
                    ),
                },
                headers={"X-Silo-Latest-Sequence": str(latest)},
            )
        if self.command_status >= 400:
            return AiohttpClientMockResponse(
                method,
                url,
                status=self.command_status,
                json={"type": "conflict", "detail": "no realtime lane"},
            )
        return AiohttpClientMockResponse(
            method,
            url,
            status=self.command_status,
            json=payloads.receipt_payload(payload["command_id"], payload["sequence"]),
        )

    async def _scan_response(self, method, url, data):
        self.scan_calls.append(dict(data))
        if self.scan_status >= 400:
            return AiohttpClientMockResponse(
                method,
                url,
                status=self.scan_status,
                json={"type": "not_found", "detail": "unknown library"},
            )
        return AiohttpClientMockResponse(method, url, status=202, json={"queued": True})


@pytest.fixture
def silo(aioclient_mock) -> SiloMock:
    """Return the fake Silo server."""
    return SiloMock(aioclient_mock)


def _make_entry(**kwargs) -> MockConfigEntry:
    """Build a config entry pointing at the fake server."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Silo (silo.test)",
        data={
            CONF_URL: MOCK_URL,
            CONF_API_KEY: MOCK_API_KEY,
            CONF_VERIFY_SSL: False,
        },
        unique_id=INSTALLATION_ID,
        **kwargs,
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry pointing at the fake server."""
    return _make_entry()


@pytest.fixture
def entry_factory():
    """Return a factory to build entries with options."""
    return _make_entry
