"""SVP BV API client for district heating data."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import date
from typing import Any
from urllib.parse import unquote

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://mijn.svpbv.nl"
CUSTOMER_APP = f"{BASE_URL}/CustomerApp"

# Known API version tokens (from HAR capture, April 2026).
# The server still returns data when stale; it just flags hasApiVersionChanged=true.
_KNOWN_API_VERSIONS = {
    "login":          "OW6SzyxPDcdFr8DWQcIgNA",
    "month_usage":    "H1Ow1vF8XRXDNL0Vs1eI_A",
    "screen_data":    "s85eTypaQlTSUL033FuyOQ",
    "connection":     "D8fVmPEMS3ny4t+5atpDlA",
    "chart_data":     "12EJ0CgyhUv5b+qIKiFw1g",
    "day_chart_data": "c4Xnnb2eEFmkw7enMYqLGQ",
}

_BASE_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "nl-NL,nl;q=0.9",
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/22H123"
    ),
    "outsystems-locale": "en-US",
}


def _request_token() -> str:
    return str(random.randint(10**15, 10**16 - 1))


def _extract_csrf(cookies: aiohttp.CookieJar) -> str | None:
    for cookie in cookies:
        if cookie.key == "nr2Users":
            raw = unquote(cookie.value)
            for part in raw.split(";"):
                part = part.strip()
                if part.startswith("crf="):
                    return part[4:]
    return None


class SVPBVAuthError(Exception):
    """Raised when authentication fails."""


class SVPBVApiError(Exception):
    """Raised when an API call fails."""


class SVPBVApiClient:
    """Async client for the SVP BV customer portal API."""

    def __init__(self, username: str, password: str, session: aiohttp.ClientSession, device_uuid: str) -> None:
        self._username = username
        self._password = password
        self._session = session
        self._device_uuid = device_uuid
        self._module_version: str = ""
        self._api_versions: dict[str, str] = {}
        self._authenticated = False

    def _api_version(self, key: str) -> str:
        return self._api_versions.get(key, self._module_version)

    def _csrf(self) -> str:
        return _extract_csrf(self._session.cookie_jar) or ""

    def _headers(self) -> dict[str, str]:
        return {
            **_BASE_HEADERS,
            "outsystems-device-uuid": self._device_uuid,
            "outsystems-request-token": _request_token(),
            "x-csrftoken": self._csrf(),
        }

    async def _fetch_module_version(self) -> str:
        ts = int(time.time() * 1000)
        async with self._session.get(
            f"{CUSTOMER_APP}/moduleservices/moduleversioninfo",
            params={str(ts): ""},
            headers={**_BASE_HEADERS, "outsystems-device-uuid": self._device_uuid},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            return data.get("versionToken", "")

    async def async_login(self) -> None:
        """Authenticate with the SVP BV portal."""
        _LOGGER.debug("SVP BV: fetching session cookie")
        async with self._session.get(
            f"{CUSTOMER_APP}/",
            headers={**_BASE_HEADERS, "outsystems-device-uuid": self._device_uuid, "Accept": "text/html,*/*"},
            allow_redirects=True,
        ) as resp:
            _LOGGER.debug("SVP BV: session GET status %s", resp.status)

        self._module_version = await self._fetch_module_version()
        self._api_versions = dict(_KNOWN_API_VERSIONS)
        _LOGGER.debug("SVP BV: module version %s", self._module_version)

        csrf = self._csrf()
        _LOGGER.debug("SVP BV: CSRF after session init: %s", csrf or "(empty)")

        payload = {
            "versionInfo": {"moduleVersion": self._module_version, "apiVersion": self._api_version("login")},
            "viewName": "Common.Login",
            "inputParameters": {
                "Username": self._username,
                "Password": self._password,
            },
        }
        async with self._session.post(
            f"{CUSTOMER_APP}/screenservices/CustomerApp/Common/Login/ActionDoLogin",
            json=payload,
            headers=self._headers(),
        ) as resp:
            if resp.status != 200:
                raise SVPBVAuthError(f"Login failed with HTTP {resp.status}")
            body = await resp.json(content_type=None)

        if body.get("exception"):
            raise SVPBVAuthError(f"Login rejected: {body['exception'].get('message', body['exception'])}")

        self._authenticated = True
        _LOGGER.debug("SVP BV: login successful for %s", self._username)

    async def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            await self.async_login()

    async def _post(self, path: str, api_key: str, screen_vars: dict | None = None, view_name: str = "MainFlow.Home") -> dict[str, Any]:
        """POST to an OutSystems screen service and return .data."""
        await self._ensure_authenticated()

        payload: dict = {
            "versionInfo": {"moduleVersion": self._module_version, "apiVersion": self._api_version(api_key)},
            "viewName": view_name,
        }
        if screen_vars is not None:
            payload["screenData"] = {"variables": screen_vars}

        async with self._session.post(
            f"{CUSTOMER_APP}{path}",
            json=payload,
            headers=self._headers(),
        ) as resp:
            if resp.status == 403:
                _LOGGER.debug("SVP BV: session expired, re-authenticating")
                self._authenticated = False
                await self.async_login()
                async with self._session.post(
                    f"{CUSTOMER_APP}{path}",
                    json=payload,
                    headers=self._headers(),
                ) as resp2:
                    resp2.raise_for_status()
                    body = await resp2.json(content_type=None)
            else:
                resp.raise_for_status()
                body = await resp.json(content_type=None)

        if "data" not in body:
            raise SVPBVApiError(f"Unexpected response from {path}: {body}")
        return body["data"]

    async def _fetch_month_usage(self) -> dict[str, Any]:
        data = await self._post(
            "/screenservices/CustomerApp/MainFlow/Home/DataActionMonthConsumptionAndSmartMeter",
            "month_usage",
            {"ShowMessageBox": False},
        )
        return {
            "month_usage_gj": _to_float(data.get("MonthUsage")),
            "has_smart_meter": bool(data.get("HasSmartMeterActive", False)),
        }

    async def _fetch_screen_data(self) -> dict[str, Any]:
        data = await self._post(
            "/screenservices/CustomerApp/MainFlow/Home/DataActionScreenData",
            "screen_data",
            {"ShowMessageBox": False},
        )
        return {
            "customer_name": data.get("CustomerName") or "",
            "advance_amount_eur": _to_float(data.get("CurrentAdvanceAmount")),
        }

    async def _fetch_connection(self) -> dict[str, Any]:
        data = await self._post(
            "/screenservices/CustomerApp/Common/CurrentAddress/DataActionGetConnection",
            "connection",
            {"ChangeBoolean": False, "_changeBooleanInDataFetchStatus": 1},
        )
        return {
            "address": data.get("CurrentAddress2") or "",
            "connection_active": bool(data.get("IsActive", False)),
        }

    async def _fetch_chart_data(self) -> dict[str, Any]:
        data = await self._post(
            "/screenservices/Consumption_CW/WebBlocks/YearOverview/DataActionGetChartData",
            "chart_data",
            {
                "Date": str(date.today()),
                "YearComparison": False,
                "IsInitialized": False,
                "TotalConsumption": "0",
                "IsMobile": True,
                "_isMobileInDataFetchStatus": 1,
                "ChangeBoolean": False,
                "_changeBooleanInDataFetchStatus": 1,
            },
        )
        chart_list = data.get("ChartData", {}).get("List") or []
        monthly: dict[str, float] = {}
        for item in chart_list:
            label = (item.get("Label") or "").lower()
            value = _to_float(item.get("Value"))
            if label and value is not None:
                monthly[label] = value

        total = _to_float(data.get("Total")) or (sum(monthly.values()) if monthly else 0.0)
        return {
            "monthly": monthly,
            "total_gj": total,
            "contract_start": data.get("ContractStartDate") or "",
            "contract_end": data.get("ContractEndDate") or "",
        }

    async def _fetch_day_data(self, day: str | None = None) -> dict[str, Any]:
        if day is None:
            day = str(date.today())
        data = await self._post(
            "/screenservices/Consumption_CW/WebBlocks/DayOverview/DataActionGetChartData",
            "day_chart_data",
            {
                "Date": day,
                "IsInitialized": False,
                "TotalConsumption": "0",
                "IsMobile": True,
                "_isMobileInDataFetchStatus": 1,
                "IsScroll": True,
                "_isScrollInDataFetchStatus": 1,
                "ChangeBoolean": False,
                "_changeBooleanInDataFetchStatus": 1,
            },
            view_name="MainFlow.Consumption",
        )
        points = data.get("ChartData", {}).get("List") or []
        hourly: dict[str, float] = {}
        for p in points:
            label = str(p.get("Label") or "")
            value = _to_float(p.get("Value"))
            if label and value is not None:
                hourly[label] = value
        return {
            "today_total_gj": sum(hourly.values()),
            "today_hourly": hourly,
        }

    async def async_get_all_data(self) -> dict[str, Any]:
        """Fetch all data, re-logging in each time to ensure a fresh session."""
        self._authenticated = False
        await self.async_login()
        month_usage, screen_data, connection, chart_data, day_data = await asyncio.gather(
            self._fetch_month_usage(),
            self._fetch_screen_data(),
            self._fetch_connection(),
            self._fetch_chart_data(),
            self._fetch_day_data(),
        )
        return {**month_usage, **screen_data, **connection, **chart_data, **day_data}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
