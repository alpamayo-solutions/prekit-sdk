"""Authentication providers for the PREKIT SDK.

Vendors the core auth logic from prekit_auth (base, oauth, api_key) and adds
Azure/Entra ID support via MSAL for interactive browser-based login.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod

from prekit_edge_node_api import ApiClient, Configuration
from prekit_edge_node_api.rest import RESTResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base (vendored from utils/prekit_auth/base.py)
# ---------------------------------------------------------------------------

class AuthProvider(ABC):
    """Base class for authentication providers."""

    name: str

    @abstractmethod
    def configure(self, config: Configuration) -> None:
        """Apply credentials to the API client configuration."""

    def refresh_if_needed(self) -> None:
        """Refresh credentials if expired or near expiry."""

    def force_refresh(self) -> None:
        """Unconditionally refresh credentials."""
        self.refresh_if_needed()


# ---------------------------------------------------------------------------
# AutoRefreshApiClient (vendored from utils/prekit_auth/client.py)
# ---------------------------------------------------------------------------

class AutoRefreshApiClient(ApiClient):
    """ApiClient that automatically refreshes expired OAuth tokens."""

    DEFAULT_TIMEOUT = (10, 30)

    def __init__(self, configuration: Configuration, auth_provider: AuthProvider) -> None:
        super().__init__(configuration=configuration)
        self._auth_provider = auth_provider
        self._patch_ssl_context()

    def _patch_ssl_context(self) -> None:
        """Patch the REST client's pool manager with a permissive SSL context.

        Python 3.13+ enforces key usage extensions on CA certificates, which
        breaks with some private PKI certs. This creates an SSL context that
        loads the CA cert but doesn't enforce key usage checks.
        """
        import ssl

        ca_cert = self.configuration.ssl_ca_cert
        if not ca_cert or not self.configuration.verify_ssl:
            return

        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(ca_cert)
            # Replace the pool manager with one using our custom context
            import urllib3
            self.rest_client.pool_manager = urllib3.PoolManager(
                ssl_context=ctx,
                ca_certs=ca_cert,
            )
        except Exception:
            pass  # Fall back to default SSL handling

    def _sync_token(self) -> None:
        token = self._auth_provider._access_token if hasattr(self._auth_provider, "_access_token") else None
        if token and token != self.configuration.access_token:
            self.configuration.access_token = token

    def call_api(
        self, method, url, header_params=None, body=None,
        post_params=None, _request_timeout=None,
    ) -> RESTResponse:
        if _request_timeout is None:
            _request_timeout = self.DEFAULT_TIMEOUT

        self._auth_provider.refresh_if_needed()
        self._sync_token()

        response = super().call_api(method, url, header_params, body, post_params, _request_timeout)

        if response.status == 403:
            response.read()
            body_text = response.data.decode("utf-8", errors="replace") if response.data else ""
            if "Signature has expired" in body_text:
                logger.info("Token expired, refreshing and retrying %s %s", method, url)
                self._auth_provider.force_refresh()
                self._sync_token()
                if header_params and "Authorization" in header_params:
                    header_params["Authorization"] = f"Bearer {self.configuration.access_token}"
                response = super().call_api(method, url, header_params, body, post_params, _request_timeout)

        return response


# ---------------------------------------------------------------------------
# API Key Provider
# ---------------------------------------------------------------------------

class ApiKeyAuthProvider(AuthProvider):
    """Authenticates using a static API key (X-API-Key header)."""

    name = "api_key"

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._access_token: str | None = None

    def configure(self, config: Configuration) -> None:
        config.api_key = {"ApiKeyAuth": self._key}


# ---------------------------------------------------------------------------
# OAuth Provider (Keycloak client_credentials)
# ---------------------------------------------------------------------------

class OAuthAuthProvider(AuthProvider):
    """Authenticates using Keycloak client_credentials grant."""

    name = "oauth"

    def __init__(
        self,
        keycloak_url: str,
        client_id: str,
        client_secret: str,
        realm: str = "prekit",
        ca_cert: str | None = None,
    ) -> None:
        self._keycloak_url = keycloak_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._realm = realm
        self._ca_cert = ca_cert
        self._access_token: str | None = None
        self._expires_at: float = 0
        self._config: Configuration | None = None

    @property
    def _token_endpoint(self) -> str:
        base = self._keycloak_url.rstrip("/")
        return f"{base}/realms/{self._realm}/protocol/openid-connect/token"

    def _fetch_token(self) -> None:
        import urllib3

        if self._ca_cert:
            http = urllib3.PoolManager(ca_certs=self._ca_cert)
        else:
            http = urllib3.PoolManager(cert_reqs="CERT_NONE")

        response = http.request(
            "POST",
            self._token_endpoint,
            fields={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            encode_multipart=False,
            timeout=urllib3.Timeout(connect=10, read=30),
        )

        if response.status != 200:
            raise RuntimeError(f"Token request failed ({response.status}): {response.data.decode()}")

        data = json.loads(response.data.decode())
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 300)
        self._expires_at = time.time() + expires_in

    def configure(self, config: Configuration) -> None:
        self._config = config
        self._fetch_token()
        config.access_token = self._access_token

    def refresh_if_needed(self) -> None:
        if time.time() >= self._expires_at - 60:
            self._fetch_token()
            if self._config is not None:
                self._config.access_token = self._access_token

    def force_refresh(self) -> None:
        self._fetch_token()
        if self._config is not None:
            self._config.access_token = self._access_token


# ---------------------------------------------------------------------------
# Azure / Entra ID Provider (MSAL interactive)
# ---------------------------------------------------------------------------

class AzureAuthProvider(AuthProvider):
    """Authenticates using Azure/Entra ID via MSAL interactive or device code flow.

    Opens a browser for login, caches tokens in memory for the session.
    """

    name = "azure"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        scopes: list[str] | None = None,
    ) -> None:
        try:
            import msal
        except ImportError:
            raise ImportError("msal is required for Azure auth: pip install msal")

        self._tenant_id = tenant_id
        self._client_id = client_id
        self._scopes = scopes or [f"{client_id}/.default"]
        self._access_token: str | None = None
        self._expires_at: float = 0
        self._config: Configuration | None = None

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        self._app = msal.PublicClientApplication(
            client_id=client_id,
            authority=authority,
        )

    def _acquire_token(self) -> None:

        # Try cached token first
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(self._scopes, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._expires_at = time.time() + result.get("expires_in", 300)
                return

        # Interactive browser login
        result = self._app.acquire_token_interactive(
            scopes=self._scopes,
            prompt="select_account",
        )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Azure login failed: {error}")

        self._access_token = result["access_token"]
        self._expires_at = time.time() + result.get("expires_in", 300)

    def configure(self, config: Configuration) -> None:
        self._config = config
        self._acquire_token()
        config.access_token = self._access_token

    def refresh_if_needed(self) -> None:
        if time.time() >= self._expires_at - 60:
            self._acquire_token()
            if self._config is not None:
                self._config.access_token = self._access_token

    def force_refresh(self) -> None:
        self._acquire_token()
        if self._config is not None:
            self._config.access_token = self._access_token
