"""Tests for the auth module: providers, auto-refresh client, and connection factories."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from prekit_edge_node_api import Configuration

from prekit_sdk.auth import (
    ApiKeyAuthProvider,
    AutoRefreshApiClient,
    AzureAuthProvider,
    OAuthAuthProvider,
)
from prekit_sdk.client import Prekit


# ---------------------------------------------------------------------------
# TestApiKeyAuthProvider
# ---------------------------------------------------------------------------


class TestApiKeyAuthProvider:
    def test_configure_sets_api_key(self):
        provider = ApiKeyAuthProvider(api_key="test-key")
        config = Configuration()
        provider.configure(config)
        assert config.api_key == {"ApiKeyAuth": "test-key"}

    def test_refresh_is_noop(self):
        provider = ApiKeyAuthProvider(api_key="test-key")
        provider.refresh_if_needed()  # Should not raise


# ---------------------------------------------------------------------------
# TestOAuthAuthProvider
# ---------------------------------------------------------------------------


class TestOAuthAuthProvider:
    def _make_provider(self, **kwargs) -> OAuthAuthProvider:
        defaults = {
            "keycloak_url": "https://auth.example.com",
            "client_id": "my-client",
            "client_secret": "my-secret",
            "realm": "prekit",
        }
        defaults.update(kwargs)
        return OAuthAuthProvider(**defaults)

    def test_token_endpoint_construction(self):
        provider = self._make_provider(keycloak_url="https://auth.example.com")
        assert provider._token_endpoint == (
            "https://auth.example.com/realms/prekit/protocol/openid-connect/token"
        )

    def test_token_endpoint_strips_trailing_slash(self):
        provider = self._make_provider(keycloak_url="https://auth.example.com/")
        assert provider._token_endpoint == (
            "https://auth.example.com/realms/prekit/protocol/openid-connect/token"
        )

    @patch("prekit_sdk.auth.urllib3", create=True)
    def test_fetch_token_success(self, _mock_urllib3_module):
        """Patch urllib3.PoolManager inside _fetch_token to return a valid token response."""
        provider = self._make_provider()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.data = json.dumps({
            "access_token": "tok-abc-123",
            "expires_in": 600,
        }).encode()

        with patch("urllib3.PoolManager") as mock_pool_cls:
            mock_pool = MagicMock()
            mock_pool.request.return_value = mock_response
            mock_pool_cls.return_value = mock_pool

            provider._fetch_token()

        assert provider._access_token == "tok-abc-123"
        assert provider._expires_at > time.time()

    def test_fetch_token_failure(self):
        provider = self._make_provider()

        mock_response = MagicMock()
        mock_response.status = 401
        mock_response.data = b"Unauthorized"

        with patch("urllib3.PoolManager") as mock_pool_cls:
            mock_pool = MagicMock()
            mock_pool.request.return_value = mock_response
            mock_pool_cls.return_value = mock_pool

            with pytest.raises(RuntimeError, match="Token request failed"):
                provider._fetch_token()

    def test_refresh_if_needed_when_expired(self):
        provider = self._make_provider()
        provider._expires_at = time.time() - 100  # Expired

        with patch.object(provider, "_fetch_token") as mock_fetch:
            provider.refresh_if_needed()
            mock_fetch.assert_called_once()

    def test_refresh_if_needed_when_valid(self):
        provider = self._make_provider()
        provider._expires_at = time.time() + 3600  # Far in the future

        with patch.object(provider, "_fetch_token") as mock_fetch:
            provider.refresh_if_needed()
            mock_fetch.assert_not_called()

    def test_force_refresh_always_fetches(self):
        provider = self._make_provider()
        provider._expires_at = time.time() + 3600  # Still valid

        with patch.object(provider, "_fetch_token") as mock_fetch:
            provider.force_refresh()
            mock_fetch.assert_called_once()

    def test_configure_fetches_and_sets_token(self):
        provider = self._make_provider()
        config = Configuration()

        with patch.object(provider, "_fetch_token") as mock_fetch:
            # Simulate what _fetch_token does
            def side_effect():
                provider._access_token = "fetched-token"

            mock_fetch.side_effect = side_effect
            provider.configure(config)

        mock_fetch.assert_called_once()
        assert config.access_token == "fetched-token"


# ---------------------------------------------------------------------------
# TestAutoRefreshApiClient
# ---------------------------------------------------------------------------


class TestAutoRefreshApiClient:
    def _make_client(self, auth_provider=None):
        config = Configuration(host="https://test.local")
        config.verify_ssl = False  # Avoid SSL patching complications

        if auth_provider is None:
            auth_provider = MagicMock()
            auth_provider._access_token = "test-token"

        client = AutoRefreshApiClient(configuration=config, auth_provider=auth_provider)
        return client, auth_provider

    def test_call_api_refreshes_token(self):
        client, auth_provider = self._make_client()

        mock_response = MagicMock()
        mock_response.status = 200

        with patch.object(
            AutoRefreshApiClient.__bases__[0], "call_api", return_value=mock_response
        ):
            result = client.call_api("GET", "/test")

        auth_provider.refresh_if_needed.assert_called_once()
        assert result.status == 200

    def test_call_api_retries_on_expired_signature(self):
        client, auth_provider = self._make_client()

        # First response: 403 with "Signature has expired"
        first_response = MagicMock()
        first_response.status = 403
        first_response.data = b"Signature has expired"

        # Second response: 200 OK
        second_response = MagicMock()
        second_response.status = 200

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_response
            return second_response

        with patch.object(
            AutoRefreshApiClient.__bases__[0], "call_api", side_effect=side_effect
        ):
            result = client.call_api("GET", "/test")

        auth_provider.force_refresh.assert_called_once()
        assert result.status == 200

    def test_call_api_no_retry_on_403_without_signature(self):
        client, auth_provider = self._make_client()

        mock_response = MagicMock()
        mock_response.status = 403
        mock_response.data = b"Forbidden: insufficient permissions"

        with patch.object(
            AutoRefreshApiClient.__bases__[0], "call_api", return_value=mock_response
        ):
            result = client.call_api("GET", "/test")

        auth_provider.force_refresh.assert_not_called()
        assert result.status == 403

    def test_default_timeout_applied(self):
        client, _ = self._make_client()

        captured_timeout = {}

        def capture_call(method, url, header_params, body, post_params, _request_timeout):
            captured_timeout["value"] = _request_timeout
            resp = MagicMock()
            resp.status = 200
            return resp

        with patch.object(
            AutoRefreshApiClient.__bases__[0], "call_api", side_effect=capture_call
        ):
            client.call_api("GET", "/test", _request_timeout=None)

        assert captured_timeout["value"] == AutoRefreshApiClient.DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# TestPrekitConnect
# ---------------------------------------------------------------------------


class TestPrekitConnect:
    @patch("prekit_sdk.client.AutoRefreshApiClient")
    @patch("prekit_sdk.client.ApiKeyAuthProvider")
    def test_connect_with_api_key(self, mock_provider_cls, mock_client_cls):
        mock_provider = MagicMock()
        mock_provider_cls.return_value = mock_provider

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api

        result = Prekit.connect("https://edge.local", api_key="my-key")

        mock_provider_cls.assert_called_once_with(api_key="my-key")
        mock_provider.configure.assert_called_once()
        assert isinstance(result, Prekit)

    @patch("prekit_sdk.client.AutoRefreshApiClient")
    @patch("prekit_sdk.client.OAuthAuthProvider")
    def test_connect_with_oauth(self, mock_provider_cls, mock_client_cls):
        mock_provider = MagicMock()
        mock_provider_cls.return_value = mock_provider

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api

        result = Prekit.connect(
            "https://edge.local",
            client_id="cid",
            client_secret="csec",
            keycloak_url="https://auth.local",
        )

        mock_provider_cls.assert_called_once_with(
            keycloak_url="https://auth.local",
            client_id="cid",
            client_secret="csec",
            realm="prekit",
            ca_cert=None,
        )
        mock_provider.configure.assert_called_once()
        assert isinstance(result, Prekit)

    @patch("prekit_sdk.client.AutoRefreshApiClient")
    @patch("prekit_sdk.client.AzureAuthProvider")
    def test_connect_with_azure(self, mock_provider_cls, mock_client_cls):
        mock_provider = MagicMock()
        mock_provider_cls.return_value = mock_provider

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api

        result = Prekit.connect(
            "https://edge.local",
            auth="azure",
            tenant_id="tid",
            client_id="cid",
        )

        mock_provider_cls.assert_called_once_with(tenant_id="tid", client_id="cid")
        mock_provider.configure.assert_called_once()
        assert isinstance(result, Prekit)

    def test_connect_no_auth_raises(self):
        with pytest.raises(ValueError, match="No authentication method provided"):
            Prekit.connect("https://edge.local")

    def test_connect_azure_missing_tenant_raises(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            Prekit.connect("https://edge.local", auth="azure")

    def test_connect_azure_missing_client_id_raises(self):
        with pytest.raises(ValueError, match="client_id is required"):
            Prekit.connect("https://edge.local", auth="azure", tenant_id="tid")


# ---------------------------------------------------------------------------
# TestPrekitConnectFromEnv
# ---------------------------------------------------------------------------


class TestPrekitConnectFromEnv:
    @patch.object(Prekit, "connect")
    def test_connect_from_env_api_key(self, mock_connect, monkeypatch):
        monkeypatch.setenv("PREKIT_URL", "https://edge.local")
        monkeypatch.setenv("API_KEY", "env-key-123")
        monkeypatch.setenv("PREKIT_AUTH_METHOD", "api_key")

        Prekit.connect_from_env()

        mock_connect.assert_called_once_with(
            url="https://edge.local",
            api_key="env-key-123",
            verify_ssl=True,
            ca_cert=None,
        )

    def test_connect_from_env_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv("PREKIT_URL", raising=False)
        with pytest.raises(ValueError, match="PREKIT_URL environment variable is required"):
            Prekit.connect_from_env()

    def test_connect_from_env_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setenv("PREKIT_URL", "https://edge.local")
        monkeypatch.setenv("PREKIT_AUTH_METHOD", "api_key")
        monkeypatch.delenv("API_KEY", raising=False)

        with pytest.raises(ValueError, match="API_KEY environment variable is required"):
            Prekit.connect_from_env()

    def test_connect_from_env_unknown_method_raises(self, monkeypatch):
        monkeypatch.setenv("PREKIT_URL", "https://edge.local")
        monkeypatch.setenv("PREKIT_AUTH_METHOD", "magic_auth")

        with pytest.raises(ValueError, match="Unknown PREKIT_AUTH_METHOD"):
            Prekit.connect_from_env()
