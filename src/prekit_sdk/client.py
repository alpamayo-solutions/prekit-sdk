"""Main SDK client — Prekit class with connection methods and manager access."""

from __future__ import annotations

import os
from typing import Any

import prekit_edge_node_api as prekit

from .auth import (
    ApiKeyAuthProvider,
    AutoRefreshApiClient,
    AzureAuthProvider,
    OAuthAuthProvider,
)
from .managers import ElementManager, SignalManager, TagContextManager, TagManager


class Prekit:
    """User-friendly client for the PREKIT edge computing platform.

    Provides Django-style managers for browsing and managing assets,
    tree visualization, and historian data access.
    """

    def __init__(self, api: AutoRefreshApiClient, hub_url: str = "", ca_cert: str | None = None) -> None:
        self._api = api
        self._hub_url = hub_url
        self._ca_cert = ca_cert
        self._elements: ElementManager | None = None
        self._signals: SignalManager | None = None
        self._tags: TagManager | None = None
        self._tag_contexts: TagContextManager | None = None

    @property
    def api(self) -> AutoRefreshApiClient:
        """Raw API client (escape hatch for direct API calls)."""
        return self._api

    # --- Lazy managers ---

    @property
    def elements(self) -> ElementManager:
        """Manager for SystemElement resources."""
        if self._elements is None:
            self._elements = ElementManager(self)
        return self._elements

    @property
    def signals(self) -> SignalManager:
        """Manager for Signal resources."""
        if self._signals is None:
            self._signals = SignalManager(self)
        return self._signals

    @property
    def tags(self) -> TagManager:
        """Manager for DataTag resources."""
        if self._tags is None:
            self._tags = TagManager(self)
        return self._tags

    @property
    def tag_contexts(self) -> TagContextManager:
        """Manager for DataTagContext resources."""
        if self._tag_contexts is None:
            self._tag_contexts = TagContextManager(self)
        return self._tag_contexts

    # --- Tree ---

    def tree(self, root: Any = None) -> Any:
        """Fetch and return the asset hierarchy as a Tree.

        Args:
            root: Optional root element (Element, ID, or None for full tree).
        """
        from .tree import build_tree_from_api

        return build_tree_from_api(self, root=root)

    # --- Data ---

    def data(
        self,
        signals: list | None = None,
        last: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> Any:
        """Fetch historian data for multiple signals.

        Args:
            signals: List of Signal wrappers or signal IDs.
            last: Relative duration (e.g., "1h", "7d").
            start: Absolute start time.
            end: Absolute end time.

        Returns:
            Pivoted DataFrame with timestamp index, one column per signal.
        """
        from .historian import fetch_multi_signal_data

        return fetch_multi_signal_data(self, signals or [], last=last, start=start, end=end)

    def query(self, sql: str) -> Any:
        """Run a SQL query against the historian database.

        Args:
            sql: SQL query string (read-only, against TimescaleDB).

        Returns:
            pandas DataFrame with query results.
        """
        import pandas as pd

        result = prekit.QueryDatabaseApi(api_client=self.api).post_one(
            data=prekit.SafeQueryRequest(query=sql)
        )
        return pd.DataFrame(result.rows, columns=result.column_names)

    def query_signals(
        self,
        system_element: str,
        signal_names: list[str],
        *,
        start: str,
        end: str,
        bucket: str = "1 minute",
        agg: str = "AVG",
    ) -> Any:
        """Query historian data for specific signals by name, using SQL.

        Args:
            system_element: Name of the parent system element.
            signal_names: List of signal names to query.
            start: Start time (ISO format or 'YYYY-MM-DD HH:MM').
            end: End time.
            bucket: TimescaleDB time_bucket interval (default: "1 minute").
            agg: Aggregation function (default: "AVG").

        Returns:
            pandas DataFrame with columns: time, signal_name, value.
        """
        import pandas as pd

        names_sql = ", ".join(f"'{n}'" for n in signal_names)
        sql = f"""
        SELECT
            time_bucket('{bucket}', m.timestamp) AS time,
            s.name AS signal_name,
            ROUND({agg}(m.value_number)::numeric, 2) AS value
        FROM historian_metric m
        JOIN edge_signal s ON s.id = m.signal_id
        JOIN edge_systemelement se ON se.id = s.system_element_id
        WHERE se.name = '{system_element}'
          AND s.name IN ({names_sql})
          AND m.timestamp >= '{start}'
          AND m.timestamp <  '{end}'
        GROUP BY time, s.name
        ORDER BY time
        """
        df = self.query(sql)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"])
        df["value"] = df["value"].astype(float)
        return df

    def get_latest(self, element: str | Any) -> dict:
        """Get latest values for all signals in a subtree.

        Args:
            element: Element name (looks up in tree) or TreeNode.

        Returns:
            Dict with 'signal_count' and 'values' list.
        """
        import json

        from .tree import TreeNode

        if isinstance(element, str):
            tree = self.tree()
            node = tree.find(element)
            if node is None:
                raise ValueError(f"Element '{element}' not found in tree")
        elif isinstance(element, TreeNode):
            node = element
        else:
            raise TypeError(f"Expected str or TreeNode, got {type(element).__name__}")

        signal_ids = node.collect_signal_ids()
        if not signal_ids:
            return {"signal_count": 0, "values": []}

        # Use _without_preload_content to get raw JSON and avoid Pydantic validation
        resp = (
            prekit.GetLatestValuesApi(api_client=self.api)
            .post_one_without_preload_content(
                data=prekit.LatestValuesRequest(signal_ids=signal_ids)
            )
        )
        return json.loads(resp.data.decode())

    def print_latest(self, element: str | Any) -> None:
        """Print latest values for all signals in a subtree."""
        latest = self.get_latest(element)
        name = element if isinstance(element, str) else getattr(element, "name", "?")
        print(f"{name} -- {latest.get('signal_count', 0)} signals\n")

        groups: dict[str, list] = {}
        for v in latest.get("values", []):
            if v.get("timestamp") is None:
                continue
            parent = v.get("system_element_name") or name
            groups.setdefault(parent, []).append(v)

        for parent, values in groups.items():
            print(f"  {parent}/")
            for v in values:
                val = v.get("value_number")
                if val is None:
                    val = v.get("value_text") or v.get("value_bool") or "n/a"
                unit = v.get("unit") or ""
                sig_name = v.get("signal_name", "?")
                print(f"    {sig_name:34s}  {str(val):>12s} {unit}")

    def whoami(self) -> dict:
        """Get the authenticated user's profile."""
        import json

        resp = prekit.UserProfileApi(api_client=self.api).get_one_without_preload_content()
        return json.loads(resp.data.decode())

    # --- Health ---

    def is_healthy(self) -> bool:
        """Check if the PREKIT API is healthy."""
        try:
            prekit.IsHealthyApi(api_client=self.api).get_one()
            return True
        except Exception:
            return False

    def health(self) -> dict:
        """Get detailed health status."""
        try:
            result = prekit.ServicesHealthApi(api_client=self.api).get_one()
            if isinstance(result, dict):
                return result
            if hasattr(result, "to_dict"):
                return result.to_dict()
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    # --- Connection factory methods ---

    @classmethod
    def connect(
        cls,
        url: str,
        *,
        # API key auth
        api_key: str | None = None,
        # OAuth (Keycloak client_credentials)
        client_id: str | None = None,
        client_secret: str | None = None,
        keycloak_url: str | None = None,
        realm: str = "prekit",
        # Azure / Entra ID
        auth: str | None = None,
        tenant_id: str | None = None,
        # SSL
        verify_ssl: bool = True,
        ca_cert: str | None = None,
    ) -> Prekit:
        """Connect to a PREKIT instance.

        Auth method is auto-detected from the provided kwargs:
        - api_key= → API key authentication
        - auth="azure" + tenant_id= → Azure/Entra ID (browser login)
        - client_id= + client_secret= → Keycloak client_credentials

        Args:
            url: Base URL of the PREKIT API (e.g., "https://edge.local").
            api_key: Static API key for X-API-Key header auth.
            client_id: OAuth client ID (Keycloak or Azure).
            client_secret: OAuth client secret (Keycloak only).
            keycloak_url: Keycloak base URL. Defaults to url + "/auth".
            realm: Keycloak realm name. Default: "prekit".
            auth: Auth method override ("azure" for Entra ID).
            tenant_id: Azure tenant ID (required for auth="azure").
            verify_ssl: Whether to verify SSL certificates. Default: True.
            ca_cert: Path to CA certificate file.

        Returns:
            Connected Prekit client.
        """
        # Normalize URL — the generated client already includes /api/v1 in
        # every endpoint path, so the host should be just the base domain.
        api_url = url.rstrip("/")

        # Build configuration
        config = prekit.Configuration(host=api_url)
        config.verify_ssl = verify_ssl
        if ca_cert:
            config.ssl_ca_cert = ca_cert

        # Determine auth provider
        if api_key is not None:
            provider = ApiKeyAuthProvider(api_key=api_key)
        elif auth == "azure":
            if not tenant_id:
                raise ValueError("tenant_id is required for Azure/Entra ID auth")
            if not client_id:
                raise ValueError("client_id is required for Azure/Entra ID auth")
            provider = AzureAuthProvider(tenant_id=tenant_id, client_id=client_id)
        elif client_id and client_secret:
            kc_url = keycloak_url or f"{url.rstrip('/')}/auth"
            provider = OAuthAuthProvider(
                keycloak_url=kc_url,
                client_id=client_id,
                client_secret=client_secret,
                realm=realm,
                ca_cert=ca_cert,
            )
        else:
            raise ValueError(
                "No authentication method provided. Use one of:\n"
                "  - api_key='...' for API key auth\n"
                "  - client_id='...' + client_secret='...' for Keycloak OAuth\n"
                "  - auth='azure' + tenant_id='...' + client_id='...' for Azure/Entra ID"
            )

        # Configure auth
        provider.configure(config)

        # Build client
        api_client = AutoRefreshApiClient(configuration=config, auth_provider=provider)

        return cls(api=api_client, hub_url=url.rstrip("/"), ca_cert=ca_cert)

    @classmethod
    def connect_from_env(cls) -> Prekit:
        """Connect using environment variables.

        Reads:
            PREKIT_URL: API base URL (required)
            PREKIT_AUTH_METHOD: "api_key", "oauth", or "azure" (default: "api_key")
            API_KEY: API key (for api_key auth)
            KEYCLOAK_URL: Keycloak URL (for oauth auth)
            KEYCLOAK_CLIENT_ID: Client ID (for oauth auth)
            KEYCLOAK_CLIENT_SECRET: Client secret (for oauth auth)
            KEYCLOAK_REALM: Realm (default: "prekit")
            AZURE_TENANT_ID: Azure tenant (for azure auth)
            AZURE_CLIENT_ID: Azure app ID (for azure auth)
            PREKIT_VERIFY_SSL: "true"/"false" (default: "true")
            CA_CERT_FILE: Path to CA cert
        """
        url = os.environ.get("PREKIT_URL", "")
        if not url:
            raise ValueError("PREKIT_URL environment variable is required")

        method = os.environ.get("PREKIT_AUTH_METHOD", "api_key")
        verify_ssl = os.environ.get("PREKIT_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        ca_cert = os.environ.get("CA_CERT_FILE", None)

        if method == "api_key":
            api_key = os.environ.get("API_KEY", "")
            if not api_key:
                raise ValueError("API_KEY environment variable is required for api_key auth")
            return cls.connect(url=url, api_key=api_key, verify_ssl=verify_ssl, ca_cert=ca_cert)

        elif method == "oauth":
            return cls.connect(
                url=url,
                client_id=os.environ.get("KEYCLOAK_CLIENT_ID", ""),
                client_secret=os.environ.get("KEYCLOAK_CLIENT_SECRET", ""),
                keycloak_url=os.environ.get("KEYCLOAK_URL", ""),
                realm=os.environ.get("KEYCLOAK_REALM", "prekit"),
                verify_ssl=verify_ssl,
                ca_cert=ca_cert,
            )

        elif method == "azure":
            return cls.connect(
                url=url,
                auth="azure",
                tenant_id=os.environ.get("AZURE_TENANT_ID", ""),
                client_id=os.environ.get("AZURE_CLIENT_ID", ""),
                verify_ssl=verify_ssl,
                ca_cert=ca_cert,
            )

        else:
            raise ValueError(f"Unknown PREKIT_AUTH_METHOD: {method}")

    def __repr__(self) -> str:
        host = self.api.configuration.host if self.api else "not connected"
        return f"<Prekit: {host}>"
