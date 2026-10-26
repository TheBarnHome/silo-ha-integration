"""Tests for the Silo API client."""

from __future__ import annotations

import pytest
from custom_components.silo.api import (
    SiloAuthError,
    SiloClient,
    SiloConflictError,
    SiloConnectionError,
    SiloNotFoundError,
    SiloPermissionError,
    SiloRateLimitError,
    SiloServerError,
    SiloUnsupportedApiError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from . import data
from .const import MOCK_API_KEY, MOCK_URL

BASE = f"{MOCK_URL}/api/v2"


@pytest.fixture
async def client(hass, aioclient_mock):
    """Return a client bound to a mocked session."""
    return SiloClient(
        async_get_clientsession(hass, verify_ssl=False), MOCK_URL, MOCK_API_KEY
    )


async def test_sessions_follow_the_cursor(client, aioclient_mock):
    """A page with has_more is followed with its opaque cursor."""
    pages = [
        data.sessions_payload([data.movie_session()], has_more=True, next_cursor="abc"),
        data.sessions_payload([data.episode_session(session_id="11")]),
    ]

    async def _responses(method, url, payload):
        return AiohttpClientMockResponse(method, url, json=pages.pop(0))

    aioclient_mock.get(f"{BASE}/admin/sessions", side_effect=_responses)

    sessions = await client.async_sessions()

    assert [session["session_id"] for session in sessions] == ["10", "11"]
    second_url = str(aioclient_mock.mock_calls[1][1])
    assert "cursor=abc" in second_url


async def test_sessions_stop_on_an_unexpected_page(client, aioclient_mock):
    """A page without page info ends the walk instead of looping."""
    aioclient_mock.get(f"{BASE}/admin/sessions", json={"items": [data.movie_session()]})

    sessions = await client.async_sessions()

    assert len(sessions) == 1


async def test_check_api_refuses_another_major(client, aioclient_mock):
    """The client speaks API v2 only."""
    aioclient_mock.get(
        f"{BASE}/system/info", json=data.system_info_payload(api_major=3)
    )

    with pytest.raises(SiloUnsupportedApiError):
        await client.async_check_api()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, SiloAuthError),
        (403, SiloPermissionError),
        (404, SiloNotFoundError),
        (500, SiloServerError),
        (503, SiloServerError),
    ],
)
async def test_statuses_map_to_typed_errors(client, aioclient_mock, status, error):
    """Every status the integration reacts to maps to one exception."""
    aioclient_mock.get(
        f"{BASE}/admin/sessions",
        status=status,
        json={"type": "problem", "detail": "refused"},
    )

    with pytest.raises(error, match="refused"):
        await client.async_sessions()


async def test_rate_limit_carries_retry_after(client, aioclient_mock):
    """A 429 exposes the advertised delay."""
    aioclient_mock.get(
        f"{BASE}/admin/sessions",
        status=429,
        json={"type": "rate_limited", "detail": "slow down"},
        headers={"Retry-After": "12"},
    )

    with pytest.raises(SiloRateLimitError) as err:
        await client.async_sessions()

    assert err.value.retry_after == 12.0


async def test_connection_error_is_typed(client, aioclient_mock):
    """A network failure is reported as a connection error."""
    aioclient_mock.get(f"{BASE}/admin/sessions", exc=OSError("boom"))

    with pytest.raises(SiloConnectionError):
        await client.async_sessions()


async def test_command_allocates_an_identity(client, aioclient_mock):
    """A command carries a UUID, a sequence and the deadline."""
    aioclient_mock.post(
        f"{BASE}/admin/sessions/10/pause",
        status=202,
        json=data.receipt_payload("0" * 36, 1),
    )

    receipt = await client.async_command("10", "pause")

    assert receipt["outcome"] == "applied"
    call_payload = aioclient_mock.mock_calls[0][2]
    assert call_payload["sequence"] >= 1
    assert len(call_payload["command_id"]) == 36
    assert call_payload["deadline_ms"] == 3000
    assert call_payload["reason"] == "Home Assistant"


async def test_command_sequences_increase(client, aioclient_mock):
    """Two commands on one session never reuse a sequence."""
    aioclient_mock.post(
        f"{BASE}/admin/sessions/10/pause",
        status=202,
        json=data.receipt_payload("0" * 36, 1),
    )

    await client.async_command("10", "pause")
    await client.async_command("10", "pause")

    sequences = [call[2]["sequence"] for call in aioclient_mock.mock_calls]
    assert sequences[0] < sequences[1]


async def test_stale_sequence_is_retried_above_the_server_value(client, aioclient_mock):
    """A stale refusal is retried once with the same command identity."""
    calls: list[dict] = []

    async def _responses(method, url, payload):
        calls.append(payload)
        if len(calls) == 1:
            return AiohttpClientMockResponse(
                method,
                url,
                status=409,
                json={"type": "conflict", "detail": "sequence behind"},
                headers={"X-Silo-Latest-Sequence": "41"},
            )
        return AiohttpClientMockResponse(
            method,
            url,
            status=202,
            json=data.receipt_payload(payload["command_id"], payload["sequence"]),
        )

    aioclient_mock.post(f"{BASE}/admin/sessions/10/pause", side_effect=_responses)

    await client.async_command("10", "pause")

    assert calls[1]["sequence"] == 42
    assert calls[0]["command_id"] == calls[1]["command_id"]


async def test_conflict_without_sequence_is_not_retried(client, aioclient_mock):
    """A conflict without the sequence header (no realtime lane) is raised."""
    aioclient_mock.post(
        f"{BASE}/admin/sessions/10/pause",
        status=409,
        json={"type": "conflict", "detail": "no realtime connection"},
    )

    with pytest.raises(SiloConflictError) as err:
        await client.async_command("10", "pause")

    assert err.value.latest_sequence is None
    assert len(aioclient_mock.mock_calls) == 1


async def test_message_command_carries_the_text(client, aioclient_mock):
    """The message action sends the text and the optional title."""
    aioclient_mock.post(
        f"{BASE}/admin/sessions/10/message",
        status=202,
        json=data.receipt_payload("0" * 36, 1),
    )

    await client.async_command("10", "message", message="Bonjour", title="Maison")

    payload = aioclient_mock.mock_calls[0][2]
    assert payload["message"] == "Bonjour"
    assert payload["title"] == "Maison"


async def test_scan_posts_the_library(client, aioclient_mock):
    """The scan action forwards the library and the optional path."""
    aioclient_mock.post(f"{BASE}/scan", status=202, json={"queued": True})

    await client.async_scan("3", "/media/films")

    assert aioclient_mock.mock_calls[0][2] == {
        "library_id": "3",
        "path": "/media/films",
    }
