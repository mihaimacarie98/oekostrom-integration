"""API client for oekostrom AG customer portal."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

import aiohttp
from yarl import URL

from .const import API_BASE, API_PORTAL_PAGE, API_PROXY, API_ENV, PORTAL_NAME, USER_AGENT

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Only alphanumeric endpoint names are valid — prevents injection via
# user-controlled data reaching the proxy's endpoint parameter.
_VALID_ENDPOINT = re.compile(r"^[A-Za-z]{1,50}$")

# Pattern to extract the proxy_login_token from the portal HTML.
_LOGIN_TOKEN_RE = re.compile(r'proxy_login_token\s*=\s*"([^"]+)"')


def _is_safe_token(token: Any) -> bool:
    """Validate that a token is a non-empty printable string.

    Avoids forwarding unexpected types or control characters into request
    query params and cookies if upstream responses are malformed.
    """
    return (
        isinstance(token, str)
        and 1 <= len(token) <= 512
        and all(ch.isprintable() and not ch.isspace() for ch in token)
    )


class OekostromApiError(Exception):
    """Base exception for API errors."""


class OekostromAuthError(OekostromApiError):
    """Authentication error."""


class OekostromApi:
    """Client for the oekostrom AG customer portal API.

    Uses its own aiohttp.ClientSession with a real cookie jar because
    Home Assistant's shared session uses DummyJar (no cookies).
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password_hash = hashlib.md5(password.encode()).hexdigest()
        self._session: aiohttp.ClientSession | None = None
        self._login_token: str | None = None
        self._session_guid: str | None = None
        self._user_data: dict[str, Any] | None = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def user_data(self) -> dict[str, Any] | None:
        """Return cached user data from last authentication."""
        return self._user_data

    async def _fetch_login_token(self) -> None:
        """Fetch the proxy_login_token from the portal login page."""
        session = self._ensure_session()
        try:
            async with session.get(
                API_PORTAL_PAGE, allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    raise OekostromApiError(
                        f"Portal returned HTTP {resp.status}"
                    )
                html = await resp.text()
                match = _LOGIN_TOKEN_RE.search(html)
                if not match:
                    raise OekostromApiError(
                        "Failed to obtain login token from portal page"
                    )
                self._login_token = match.group(1)
        except aiohttp.ClientError as err:
            raise OekostromApiError(f"Connection error: {err}") from err

    def _build_body(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build the request body with SessionGUID and PortalName."""
        body: dict[str, Any] = {"SessionGUID": self._session_guid}
        body["PortalName"] = PORTAL_NAME
        body.update(data)
        return body

    async def _call_endpoint(
        self,
        endpoint: str,
        data: dict[str, Any],
        use_login_token: bool = False,
    ) -> Any:
        """Call an API endpoint via the proxy."""
        if not _VALID_ENDPOINT.match(endpoint):
            raise OekostromApiError(f"Invalid endpoint name: {endpoint!r}")

        token = self._login_token if use_login_token else self._session_guid
        if not _is_safe_token(token):
            raise OekostromApiError(f"No token available for {endpoint}")

        params = {
            "api": API_ENV,
            "endpoint": endpoint,
            "token": token,
            "get_from_cache": "false",
            "save_to_cache": "false",
        }

        headers = {
            "Content-Type": "application/json",
            "Origin": API_BASE,
            "Referer": API_PORTAL_PAGE + "/",
        }

        session = self._ensure_session()
        try:
            async with session.post(
                API_PROXY,
                params=params,
                json=data,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    raise OekostromApiError(
                        f"HTTP {resp.status} from proxy for {endpoint}"
                    )

                text = await resp.text()

                if text.startswith("invalid proxy call"):
                    raise OekostromApiError(
                        f"Proxy rejected call to {endpoint}"
                    )

                try:
                    result = json.loads(text)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise OekostromApiError(
                        f"Invalid JSON from {endpoint}"
                    ) from exc

                if isinstance(result, dict):
                    status = result.get("Status")
                    if status == "SESSIONTIMEOUT":
                        raise OekostromAuthError("Session timed out")

                return result
        except aiohttp.ClientError as err:
            raise OekostromApiError(
                f"Connection error calling {endpoint}: {err}"
            ) from err

    async def authenticate(self) -> dict[str, Any]:
        """Authenticate with the portal and return user data."""
        await self._fetch_login_token()

        result = await self._call_endpoint(
            "UserLogin",
            {
                "Username": self._username,
                "Password": self._password_hash,
                "PortalName": PORTAL_NAME,
            },
            use_login_token=True,
        )

        if not isinstance(result, dict):
            raise OekostromAuthError("Login returned unexpected response")

        status = result.get("Status")
        if status not in ("OK", "EMAILOK"):
            raise OekostromAuthError(f"Login failed with status: {status}")

        session_guid = result.get("SessionGUID")
        if not _is_safe_token(session_guid):
            raise OekostromAuthError("Login returned invalid session token")

        self._session_guid = session_guid
        self._user_data = result

        # Set the oekp_l cookie so subsequent calls work
        session = self._ensure_session()
        session.cookie_jar.update_cookies(
            {"oekp_l": self._session_guid},
            URL(API_BASE),
        )

        _LOGGER.debug(
            "Authenticated successfully with %d account(s)",
            len(result.get("AccountIds", [])),
        )

        return result

    async def get_products(self, acc_id: int) -> list[dict[str, Any]]:
        """Get product/tariff information for an account."""
        result = await self._call_endpoint(
            "GetProducts",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, list):
            return result
        return []

    async def get_installments(self, acc_id: int) -> dict[str, Any]:
        """Get installment/payment plan data for an account."""
        result = await self._call_endpoint(
            "GetInstallments",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_invoices(self, acc_id: int) -> list[dict[str, Any]]:
        """Get invoice list for an account."""
        result = await self._call_endpoint(
            "GetInvoices",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, list):
            return result
        return []

    async def get_invoice_summary(self, acc_id: int) -> dict[str, Any]:
        """Get invoice summary for an account."""
        result = await self._call_endpoint(
            "GetInvoiceSummary",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_price_infos(self, acc_id: int) -> dict[str, Any]:
        """Get price information for an account."""
        result = await self._call_endpoint(
            "GetPriceInfos",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_dashboard(self, acc_id: int) -> dict[str, Any]:
        """Get dashboard data for an account."""
        result = await self._call_endpoint(
            "GetDashboard",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_smart_meter(self, acc_id: int) -> dict[str, Any]:
        """Get smart meter status for an account."""
        result = await self._call_endpoint(
            "GetSmartMeter",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_bonus_point_data(self, acc_id: int) -> dict[str, Any]:
        """Get bonus point data for an account."""
        result = await self._call_endpoint(
            "GetBonusPointData",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_load_profile_widget(self, acc_id: int) -> dict[str, Any]:
        """Get load profile widget (consumption overview)."""
        result = await self._call_endpoint(
            "GetLoadProfileWidget",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_new_notifications(self, acc_id: int) -> dict[str, Any]:
        """Get new notifications for an account."""
        result = await self._call_endpoint(
            "GetNewNotifications",
            self._build_body({"AccId": acc_id}),
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_invoices(self, acc_id: int) -> list[dict[str, Any]]:
        """Get invoices for an account."""
        result = await self._call_endpoint(
            "GetInvoices",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        if isinstance(result, list):
            return result
        return []

    async def get_invoice_summary(self, acc_id: int) -> dict[str, Any]:
        """Get invoice summary for an account."""
        result = await self._call_endpoint(
            "GetInvoiceSummary",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        return result if isinstance(result, dict) else {}

    async def get_installments(self, acc_id: int) -> dict[str, Any]:
        """Get installment/payment plan info."""
        result = await self._call_endpoint(
            "GetInstallments",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        return result if isinstance(result, dict) else {}

    async def get_load_profile(
        self, acc_id: int, b_date: str, e_date: str
    ) -> Any:
        """Get load profile (energy consumption) data."""
        return await self._call_endpoint(
            "GetLoadProfile",
            {
                "SessionGUID": self._session_guid,
                "AccId": acc_id,
                "BDate": b_date,
                "EDate": e_date,
            },
        )

    async def get_load_profile_widget(self, acc_id: int) -> Any:
        """Get load profile widget data (summary)."""
        return await self._call_endpoint(
            "GetLoadProfileWidget",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )

    async def get_smart_meter(self, acc_id: int) -> dict[str, Any]:
        """Get smart meter status."""
        result = await self._call_endpoint(
            "GetSmartMeter",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        return result if isinstance(result, dict) else {}

    async def get_settlement_frequencies(self, acc_id: int) -> list[dict[str, Any]]:
        """Get settlement/billing periods."""
        result = await self._call_endpoint(
            "GetSettlementFrequencies",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        if isinstance(result, list):
            return result
        return []

    async def get_dashboard(self, acc_id: int) -> dict[str, Any]:
        """Get dashboard data."""
        result = await self._call_endpoint(
            "GetDashboard",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        return result if isinstance(result, dict) else {}

    async def get_bonus_points(self) -> dict[str, Any]:
        """Get bonus point data."""
        result = await self._call_endpoint(
            "GetBonusPointData",
            {"SessionGUID": self._session_guid},
        )
        return result if isinstance(result, dict) else {}

    async def get_device_data(self, acc_id: int) -> dict[str, Any]:
        """Get device/meter data."""
        result = await self._call_endpoint(
            "GetDeviceData",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        return result if isinstance(result, dict) else {}

    async def get_price_infos(self, acc_id: int) -> dict[str, Any]:
        """Get price information."""
        result = await self._call_endpoint(
            "GetPriceInfos",
            {"SessionGUID": self._session_guid, "AccId": acc_id},
        )
        return result if isinstance(result, dict) else {}
