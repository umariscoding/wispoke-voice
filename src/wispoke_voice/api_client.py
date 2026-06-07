"""
HTTPX-based async client for wispoke-api callbacks.

Single responsibility: HTTP transport + service JWT minting. No business logic
here — callers (tools, tenant loader) compose the right calls.

Service tokens are minted per-request with a tight 5-min TTL so a leaked
in-memory token can't be replayed for long, and we never need to refresh.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import jwt as _jwt

from wispoke_voice.config import get_settings
from wispoke_voice.observability import get_logger

logger = get_logger("wispoke.voice.api")

_JWT_ALG = "HS256"
_TOKEN_TTL = timedelta(minutes=5)
_SCOPE = "voice:internal"


class WispokeApiError(RuntimeError):
    """Raised when wispoke-api returns a non-2xx response."""

    def __init__(self, method: str, url: str, status: int, body: str):
        super().__init__(f"{method} {url} -> {status}: {body}")
        self.status = status
        self.body = body


class WispokeApiClient:
    """Async HTTP client scoped to a single voice session.

    `company_id` is captured at construction so tokens can be scoped to the
    tenant — the backend rejects mismatches as a defense-in-depth check.
    """

    __slots__ = ("_company_id", "_http", "_secret")

    def __init__(self, *, company_id: Optional[str] = None, timeout: float = 10.0) -> None:
        s = get_settings()
        self._company_id = company_id
        self._secret = s.wispoke_service_jwt_secret
        self._http = httpx.AsyncClient(base_url=s.wispoke_api_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ─── Token minting ─────────────────────────────────────────────────────

    def _mint_token(self) -> str:
        payload: Dict[str, Any] = {
            "type": "service",
            "scope": _SCOPE,
            "exp": datetime.now(timezone.utc) + _TOKEN_TTL,
        }
        if self._company_id is not None:
            payload["company_id"] = self._company_id
        return _jwt.encode(payload, self._secret, algorithm=_JWT_ALG)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._mint_token()}", "Content-Type": "application/json"}

    # ─── Request helper ────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        r = await self._http.request(method, path, headers=self._headers(), **kwargs)
        if r.status_code >= 400:
            raise WispokeApiError(method, path, r.status_code, r.text)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ─── Tenant ────────────────────────────────────────────────────────────

    async def get_tenant_config(self, company_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/voice/internal/tenant/{company_id}")

    # ─── SIP inbound — resolve dialed number → tenant ──────────────────────

    async def resolve_sip_tenant(self, e164: str) -> Dict[str, Any]:
        """Used on SIP inbound when the worker doesn't yet know the tenant.

        Mint the token with `company_id=None` (the route doesn't require a
        scoped token — see voice_internal/auth.py).
        """
        return await self._request(
            "GET", "/voice/internal/sip/resolve", params={"to": e164}
        )

    # ─── Availability ──────────────────────────────────────────────────────

    async def get_available_slots(
        self, company_id: str, date_str: str, duration_min: Optional[int] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if duration_min is not None:
            params["duration"] = duration_min
        return await self._request(
            "GET", f"/voice/internal/availability/{company_id}/slots/{date_str}", params=params
        )

    # ─── Appointments ──────────────────────────────────────────────────────

    async def create_appointment(self, company_id: str, **fields: Any) -> Dict[str, Any]:
        body = {"company_id": company_id, **{k: v for k, v in fields.items() if v is not None}}
        return await self._request("POST", "/voice/internal/appointments", json=body)

    # ─── Call logs ─────────────────────────────────────────────────────────

    async def open_call_log(
        self,
        company_id: str,
        *,
        room_name: str,
        language: str = "en",
        llm_model: Optional[str] = None,
        source: str = "browser",
        caller_ref: Optional[str] = None,
    ) -> str:
        body = {
            "company_id": company_id,
            "room_name": room_name,
            "language": language,
            "llm_model": llm_model,
            "source": source,
            "caller_ref": caller_ref,
        }
        body = {k: v for k, v in body.items() if v is not None}
        res = await self._request("POST", "/voice/internal/call-logs", json=body)
        return res["call_log_id"]

    async def finalize_call_log(
        self,
        call_log_id: str,
        *,
        transcript: List[Dict[str, Any]],
        outcome: Optional[str],
        appointment_id: Optional[str] = None,
        latency_metrics: Optional[Dict[str, Any]] = None,
        started_at_iso: Optional[str] = None,
        recording_url: Optional[str] = None,
        recording_format: Optional[str] = None,
    ) -> None:
        body = {
            "transcript": transcript,
            "outcome": outcome,
            "appointment_id": appointment_id,
            "latency_metrics": latency_metrics,
            "started_at": started_at_iso,
            "recording_url": recording_url,
            "recording_format": recording_format,
        }
        body = {k: v for k, v in body.items() if v is not None}
        await self._request("PATCH", f"/voice/internal/call-logs/{call_log_id}", json=body)
