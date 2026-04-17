import httpx
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.errors import UnifiError, ErrorCategory, status_to_category


class UnifiClient:
    """Async HTTP client for the UniFi API with API key auth, caching, and discovery logging."""

    def __init__(self, config: UnifiConfig, cache: TTLCache, discovery: DiscoveryRegistry) -> None:
        self.config = config
        self.cache = cache
        self.discovery = discovery
        self._site_id: str | None = None
        self._http = httpx.AsyncClient(
            base_url=config.unifi_host,
            headers={"X-API-Key": config.unifi_api_key},
            verify=config.unifi_verify_ssl,
            timeout=30.0,
        )

    async def get(
        self,
        path: str,
        cache_category: str | None = None,
        cache_ttl: float | None = None,
    ) -> dict:
        """GET request with optional caching."""
        resolved = await self._resolve_path(path)

        if cache_category:
            cached = self.cache.get(f"{cache_category}:{resolved}")
            if cached is not None:
                return cached

        result = await self._request("GET", resolved)

        if cache_category and cache_ttl:
            self.cache.set(f"{cache_category}:{resolved}", result, cache_ttl)

        return result

    async def get_binary(self, path: str) -> tuple[bytes, str]:
        """GET request that returns raw bytes plus content-type.

        Used for endpoints that return non-JSON payloads such as camera snapshots
        (image/jpeg) or backup files (application/octet-stream).
        """
        resolved = await self._resolve_path(path)
        try:
            response = await self._http.request("GET", resolved)
            self.discovery.log(resolved, "GET", response.status_code)

            if response.status_code >= 400:
                category = status_to_category(response.status_code)
                if category:
                    raise UnifiError(
                        category,
                        f"GET {resolved} returned {response.status_code}",
                        endpoint=resolved,
                    )
                response.raise_for_status()

            return response.content, response.headers.get("content-type", "")
        except httpx.ConnectError:
            self.discovery.log(resolved, "GET", 0)
            raise UnifiError(
                ErrorCategory.CONNECTION_ERROR,
                f"Cannot reach UniFi console at {self.config.unifi_host}",
                endpoint=resolved,
            )
        except UnifiError:
            raise
        except httpx.HTTPError as e:
            raise UnifiError(
                ErrorCategory.CONNECTION_ERROR,
                f"HTTP error: {e}",
                endpoint=resolved,
            )

    async def post(self, path: str, json: dict | None = None) -> dict:
        """POST request."""
        return await self._request("POST", await self._resolve_path(path), json=json)

    async def put(self, path: str, json: dict | None = None) -> dict:
        """PUT request."""
        return await self._request("PUT", await self._resolve_path(path), json=json)

    async def patch(self, path: str, json: dict | None = None) -> dict:
        """PATCH request."""
        return await self._request("PATCH", await self._resolve_path(path), json=json)

    async def delete(self, path: str) -> dict:
        """DELETE request."""
        return await self._request("DELETE", await self._resolve_path(path))

    def invalidate_cache(self, category: str) -> None:
        """Invalidate all cache entries for a category. Called after mutations."""
        self.cache.invalidate(category)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def _resolve_path(self, path: str) -> str:
        """Replace {site} and {site_id} placeholders.

        {site} is the legacy/V2 string identifier (e.g., 'default').
        {site_id} is the Integration API UUID, fetched lazily on first use.
        """
        resolved = path.replace("{site}", self.config.unifi_site)
        if "{site_id}" in resolved:
            site_id = await self._ensure_site_id()
            resolved = resolved.replace("{site_id}", site_id)
        return resolved

    async def _ensure_site_id(self) -> str:
        """Fetch and cache the Integration API site UUID for the configured site.

        The Integration API addresses sites by UUID rather than the legacy short
        name. We look up the site whose `internalReference` matches the configured
        `unifi_site` and cache its `id` for the lifetime of the client.
        """
        if self._site_id is not None:
            return self._site_id

        response = await self._request("GET", "/proxy/network/integration/v1/sites")
        if isinstance(response, dict):
            site_list = response.get("data", [])
        elif isinstance(response, list):
            site_list = response
        else:
            site_list = []

        for site in site_list:
            if site.get("internalReference") == self.config.unifi_site:
                site_id = site.get("id")
                if site_id:
                    self._site_id = site_id
                    return site_id

        raise UnifiError(
            ErrorCategory.NOT_FOUND,
            f"No Integration API site found with internalReference='{self.config.unifi_site}'",
            endpoint="/proxy/network/integration/v1/sites",
        )

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        """Execute an HTTP request with error handling and discovery logging."""
        try:
            response = await self._http.request(method, path, json=json)
            self.discovery.log(path, method, response.status_code)

            if response.status_code >= 400:
                category = status_to_category(response.status_code)
                if category:
                    raise UnifiError(
                        category,
                        f"{method} {path} returned {response.status_code}",
                        endpoint=path,
                    )
                response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type:
                raise UnifiError(
                    ErrorCategory.UNEXPECTED_RESPONSE,
                    f"{method} {path} returned non-JSON content-type '{content_type}' "
                    f"(status {response.status_code})",
                    endpoint=path,
                )
            return response.json()

        except httpx.ConnectError:
            self.discovery.log(path, method, 0)
            raise UnifiError(
                ErrorCategory.CONNECTION_ERROR,
                f"Cannot reach UniFi console at {self.config.unifi_host}",
                endpoint=path,
            )
        except UnifiError:
            raise
        except httpx.HTTPError as e:
            raise UnifiError(
                ErrorCategory.CONNECTION_ERROR,
                f"HTTP error: {e}",
                endpoint=path,
            )
