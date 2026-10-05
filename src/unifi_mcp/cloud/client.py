"""Async httpx client for the UniFi Site Manager cloud API (https://api.ui.com)."""

import logging
from typing import Any

import httpx

from unifi_mcp.cloud.config import CloudConfig
from unifi_mcp.errors import ErrorCategory, UnifiError, status_to_category

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 20


class CloudRateLimitError(UnifiError):
    """HTTP 429 from the cloud API. Carries the Retry-After value when present."""

    def __init__(self, message: str, endpoint: str | None, retry_after: int | None):
        super().__init__(ErrorCategory.CONNECTION_ERROR, message, endpoint=endpoint)
        self.retry_after = retry_after

    def to_dict(self) -> dict:
        result = super().to_dict()
        result["rate_limited"] = True
        if self.retry_after is not None:
            result["retry_after_seconds"] = self.retry_after
        return result


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(float(value.strip())))
    except ValueError:
        return None


def _api_message(response: httpx.Response) -> str:
    """Extract the upstream error message without echoing arbitrary bodies."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return f": {body['message'][:200]}"
    return ""


class CloudClient:
    """Read-oriented client for api.ui.com. Auth header is X-API-KEY."""

    def __init__(self, config: CloudConfig, transport: httpx.AsyncBaseTransport | None = None):
        if not config.has_key:
            raise ValueError("UNIFI_CLOUD_API_KEY is not set")
        self.base_url = config.unifi_cloud_base_url
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-KEY": config.unifi_cloud_api_key.get_secret_value(),
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"CloudClient(base_url={self.base_url!r})"

    async def get(self, path: str, params: Any = None) -> dict:
        """GET a JSON document. `params` may be a dict or a list of (key, value) tuples."""
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        """POST a JSON body (used only for read queries such as ISP metrics)."""
        return await self._request("POST", path, json=json)

    async def get_paginated(
        self,
        path: str,
        params: dict | list | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> list:
        """Follow nextToken pagination and return the concatenated `data` items."""
        base = list(params.items()) if isinstance(params, dict) else list(params or [])
        base = [(k, v) for k, v in base if v is not None]
        items: list = []
        token: str | None = None
        for page_number in range(max_pages):
            page = base + [("pageSize", str(page_size))]
            if token:
                page.append(("nextToken", token))
            body = await self.get(path, params=page)
            data = body.get("data", []) if isinstance(body, dict) else body
            if isinstance(data, list):
                items = [*items, *data]
            elif data:
                items = [*items, data]
            token = body.get("nextToken") if isinstance(body, dict) else None
            if not token:
                break
            if page_number == max_pages - 1:
                logger.warning(
                    "Site Manager pagination for %s stopped after %d pages; results are truncated",
                    path, max_pages,
                )
        return items

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, params: Any = None, json: dict | None = None) -> dict:
        try:
            response = await self._http.request(method, path, params=params, json=json)
        except httpx.TimeoutException:
            raise UnifiError(
                ErrorCategory.CONNECTION_ERROR,
                f"Timed out calling the UniFi cloud API ({method} {path})",
                endpoint=path,
            )
        except httpx.HTTPError as exc:
            raise UnifiError(
                ErrorCategory.CONNECTION_ERROR,
                f"Cannot reach the UniFi cloud API: {type(exc).__name__}",
                endpoint=path,
            )
        if response.status_code >= 400:
            raise self._map_error(method, path, response)
        try:
            return response.json()
        except ValueError:
            raise UnifiError(
                ErrorCategory.UNEXPECTED_RESPONSE,
                f"{method} {path} returned a non-JSON body (status {response.status_code})",
                endpoint=path,
            )

    @staticmethod
    def _map_error(method: str, path: str, response: httpx.Response) -> UnifiError:
        status = response.status_code
        detail = _api_message(response)
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            hint = f" Retry after {retry_after}s." if retry_after is not None else ""
            return CloudRateLimitError(
                f"{method} {path} was rate limited (429).{hint}", path, retry_after
            )
        category = status_to_category(status)
        if category is None:
            category = (
                ErrorCategory.PRODUCT_UNAVAILABLE if status in (502, 503, 504)
                else ErrorCategory.UNEXPECTED_RESPONSE
            )
        return UnifiError(category, f"{method} {path} returned {status}{detail}", endpoint=path)
