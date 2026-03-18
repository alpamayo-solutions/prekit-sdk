"""Rich wrapper models over generated Pydantic models.

Each wrapper delegates attribute access to the underlying generated model via
__getattr__, so new fields added during API client regeneration appear
automatically. The SDK adds navigation methods (verbs) that don't collide
with the generated model's field names (nouns).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .helpers import truncate_id

if TYPE_CHECKING:
    import pandas as pd


class _BaseModel:
    """Base class for all SDK wrapper models.

    Proxies attribute access to the underlying generated Pydantic model (_raw)
    and provides .help() introspection.
    """

    _type_name: str = "Object"
    _relationships: dict[str, str] = {}
    _actions: dict[str, str] = {}

    def __init__(self, raw: Any, client: Any) -> None:
        # Use object.__setattr__ to avoid triggering __getattr__
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "_client", client)

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the generated model."""
        raw = object.__getattribute__(self, "_raw")
        try:
            return getattr(raw, name)
        except AttributeError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}' "
                f"(also checked generated {type(raw).__name__})"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._raw, name, value)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _BaseModel):
            return self._raw == other._raw
        return NotImplemented

    def __hash__(self) -> int:
        return hash(getattr(self._raw, "id", id(self._raw)))

    def _get_field_names(self) -> list[str]:
        """Discover field names from the generated Pydantic model."""
        raw = self._raw
        # Pydantic v2
        if hasattr(raw, "model_fields"):
            return list(raw.model_fields.keys())
        # Pydantic v1 fallback
        if hasattr(raw, "__fields__"):
            return list(raw.__fields__.keys())
        # Last resort: instance __dict__
        return [k for k in vars(raw) if not k.startswith("_")]

    def help(self) -> None:
        """Print a structured summary of this object's fields, relationships, and actions."""
        raw = self._raw
        name = getattr(raw, "name", getattr(raw, "display_name", ""))
        obj_id = getattr(raw, "id", "")

        print(f"\n{type(raw).__name__}: {name} ({truncate_id(obj_id)})")

        # Path (if available)
        if hasattr(self, "path") and callable(self.path):
            try:
                p = self.path()
                print(f"Path: {p}")
            except Exception:
                pass

        # Fields from generated model
        fields = self._get_field_names()
        if fields:
            # Show first 8 fields, then "..."
            display = fields[:8]
            suffix = ", ..." if len(fields) > 8 else ""
            print("\nFields (from generated model):")
            print(f"  {', '.join(display)}{suffix}")

        # Relationships
        if self._relationships:
            print("\nRelationships:")
            for method, desc in self._relationships.items():
                count = ""
                try:
                    result = getattr(self, method.strip(".()"))()
                    if isinstance(result, list):
                        count = f" ({len(result)} items)"
                    elif result is not None:
                        count = f" -> {getattr(result, 'name', repr(result))}"
                    else:
                        count = " -> None"
                except Exception:
                    count = ""
                print(f"  {method:<25} {desc}{count}")

        # Actions
        if self._actions:
            print("\nActions:")
            for method, desc in self._actions.items():
                print(f"  {method:<25} {desc}")

        print(f"  {'._raw':<25} generated {type(raw).__name__} model")
        print()


class Element(_BaseModel):
    """Wraps a SystemElement with hierarchy navigation and data access."""

    _type_name = "SystemElement"
    _relationships = {
        ".signals()": "child signals",
        ".children()": "child elements",
        ".parent()": "parent element",
    }
    _actions = {
        '.data(last="1h")': "DataFrame (all child signals)",
        ".tree()": "subtree from here",
        ".update(name=...)": "patch this element",
    }

    def signals(self) -> list[Signal]:
        """Get all signals attached to this element."""
        return self._client.signals.filter(system_element=self.id)

    def children(self) -> list[Element]:
        """Get direct child elements."""
        return self._client.elements.filter(parent=self.id)

    def parent(self) -> Element | None:
        """Get the parent element, or None if this is the root."""
        parent_id = getattr(self._raw, "parent", None)
        if parent_id is None:
            return None
        try:
            return self._client.elements.get(id=parent_id)
        except Exception:
            return None

    def path(self) -> str:
        """Build the full hierarchy path: 'Factory/LineA/CNC-Mill'."""
        parts: list[str] = []
        current: Element | None = self
        seen: set[str] = set()
        while current is not None:
            cid = current.id
            if cid in seen:
                break
            seen.add(cid)
            parts.append(current.name)
            current = current.parent()
        return "/".join(reversed(parts))

    def tree(self) -> Any:
        """Get a Tree rooted at this element."""
        return self._client.tree(root=self)

    def data(self, last: str | None = None, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        """Fetch historian data for all signals on this element."""
        from .historian import fetch_element_data

        return fetch_element_data(self._client, self, last=last, start=start, end=end)

    def update(self, **kwargs: Any) -> Element:
        """Patch this element with the given fields."""
        import prekit_edge_node_api as prekit

        patched = prekit.PatchedSystemElementCreate(**kwargs)
        result = prekit.SystemElementApi(api_client=self._client.api).patch_one(id=self.id, data=patched)
        return Element(result, self._client)

    def __repr__(self) -> str:
        return f"<Element: {self.name} ({truncate_id(self.id)})>"


class Signal(_BaseModel):
    """Wraps a Signal with data access and element navigation."""

    _type_name = "Signal"
    _relationships = {
        ".element()": "parent system element",
        ".tag_contexts()": "data tag bindings",
    }
    _actions = {
        '.data(last="1h")': "DataFrame (timestamp + value)",
        ".latest()": "latest metric value",
        ".path()": "full hierarchy path",
    }

    def element(self) -> Element | None:
        """Get the parent system element."""
        elem_id = getattr(self._raw, "system_element", None)
        if elem_id is None:
            return None
        try:
            return self._client.elements.get(id=elem_id)
        except Exception:
            return None

    def path(self) -> str:
        """Full path including signal name: 'Factory/LineA/CNC-Mill/Temperature'."""
        elem = self.element()
        if elem:
            return f"{elem.path()}/{self.name}"
        return self.name

    def tag_contexts(self) -> list:
        """Get data tag contexts bound to this signal."""
        return self._client.tag_contexts.filter(signal=self.id)

    def data(self, last: str | None = None, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        """Fetch historian data for this signal."""
        from .historian import fetch_signal_data

        return fetch_signal_data(self._client, self, last=last, start=start, end=end)

    def latest(self) -> dict | None:
        """Get the latest metric value for this signal."""
        from .historian import fetch_latest

        return fetch_latest(self._client, self)

    def __repr__(self) -> str:
        return f"<Signal: {self.name} ({truncate_id(self.id)})>"


class Tag(_BaseModel):
    """Wraps a DataTag with service navigation."""

    _type_name = "DataTag"
    _relationships = {
        ".service()": "owning connector service",
    }
    _actions = {}

    def service(self) -> Any:
        """Get the connector service that owns this tag."""
        svc_id = getattr(self._raw, "service", None)
        if svc_id is None:
            return None
        # Return raw since we don't have a Service wrapper in v1
        import prekit_edge_node_api as prekit

        try:
            return prekit.ServiceApi(api_client=self._client.api).get_one(name=svc_id)
        except Exception:
            return None

    def __repr__(self) -> str:
        tag_name = getattr(self._raw, "name", getattr(self._raw, "tag_id", ""))
        return f"<Tag: {tag_name} ({truncate_id(self.id)})>"


class TagContext(_BaseModel):
    """Wraps a DataTagContext with signal/tag navigation."""

    _type_name = "DataTagContext"
    _relationships = {
        ".signal()": "bound signal",
        ".tag()": "source data tag",
    }
    _actions = {}

    def signal(self) -> Signal | None:
        """Get the signal this context is bound to."""
        sig_id = getattr(self._raw, "signal", None)
        if sig_id is None:
            return None
        try:
            return self._client.signals.get(id=sig_id)
        except Exception:
            return None

    def tag(self) -> Tag | None:
        """Get the source data tag."""
        tag_id = getattr(self._raw, "data_tag", None)
        if tag_id is None:
            return None
        try:
            return self._client.tags.get(id=tag_id)
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"<TagContext: ({truncate_id(self.id)})>"
