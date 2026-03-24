"""Django-style managers for PREKIT API resources.

Each manager provides .get(), .filter(), .all(), and .create() methods,
inspired by Django's ORM queryset API. Managers resolve API classes by name
from the generated client at init time -- no hardcoded imports of specific
API classes, so regenerating the client doesn't break the SDK.
"""

from __future__ import annotations

from typing import Any, TypeVar

import prekit_edge_node_api as prekit

from .helpers import resolve_id
from .models import Element, Signal, Tag, TagContext, _BaseModel

T = TypeVar("T", bound=_BaseModel)


class DoesNotExist(Exception):
    """Raised when .get() finds no matching object."""


class MultipleObjectsReturned(Exception):
    """Raised when .get() finds more than one matching object."""


def _apply_lookup(obj: Any, field: str, lookup: str, value: Any) -> bool:
    """Apply a single Django-style lookup to an object."""
    raw = obj._raw if hasattr(obj, "_raw") else obj
    actual = getattr(raw, field, None)

    if lookup == "exact":
        # Handle FK fields: accept object or string ID
        if hasattr(value, "id"):
            value = value.id
        elif hasattr(value, "_raw") and hasattr(value._raw, "id"):
            value = value._raw.id
        return actual == value
    elif lookup == "contains":
        return actual is not None and str(value) in str(actual)
    elif lookup == "startswith":
        return actual is not None and str(actual).startswith(str(value))
    elif lookup == "icontains":
        return actual is not None and str(value).lower() in str(actual).lower()
    elif lookup == "istartswith":
        return actual is not None and str(actual).lower().startswith(str(value).lower())
    elif lookup == "iexact":
        return actual is not None and str(actual).lower() == str(value).lower()
    return False


def _parse_lookup(key: str) -> tuple[str, str]:
    """Parse 'field__lookup' into (field, lookup). Default lookup is 'exact'."""
    lookups = ("contains", "startswith", "icontains", "istartswith", "iexact")
    for lk in lookups:
        suffix = f"__{lk}"
        if key.endswith(suffix):
            return key[: -len(suffix)], lk
    return key, "exact"


class Manager:
    """Base manager providing get/filter/all/create for a PREKIT resource type.

    API class names are resolved at init time from prekit_edge_node_api,
    so regenerating the API client doesn't require SDK changes.
    """

    api_class_name: str = ""
    model_class: type[_BaseModel] = _BaseModel

    def __init__(self, client: Any) -> None:
        self._client = client
        self._api_class = getattr(prekit, self.api_class_name)

    def _api(self) -> Any:
        """Instantiate the generated API class."""
        return self._api_class(api_client=self._client.api)

    def _wrap(self, raw: Any) -> _BaseModel:
        """Wrap a raw generated model in the SDK wrapper."""
        return self.model_class(raw, self._client)

    def _wrap_list(self, items: list) -> list:
        """Wrap a list of raw models."""
        return [self._wrap(item) for item in items]

    def all(self) -> list:
        """Fetch all objects of this type."""
        result = self._api().get_all()
        if isinstance(result, list):
            return self._wrap_list(result)
        # Handle paginated responses
        if hasattr(result, "objects"):
            return self._wrap_list(result.objects)
        if hasattr(result, "data"):
            return self._wrap_list(result.data)
        return self._wrap_list(result)

    def filter(self, **kwargs: Any) -> list:
        """Filter objects using Django-style lookups.

        Supports: name="exact", name__contains="sub", name__startswith="pre",
        name__icontains="SUB", system_element=obj_or_id, id="...", path="Factory/LineA".
        """
        # Handle 'path' lookup for elements (special case)
        path_filter = kwargs.pop("path", None)

        items = self.all()

        for key, value in kwargs.items():
            field, lookup = _parse_lookup(key)
            items = [item for item in items if _apply_lookup(item, field, lookup, value)]

        # Apply path filter for elements
        if path_filter is not None and self.model_class is Element:
            items = [item for item in items if item.path() == path_filter]

        return items

    def get(self, **kwargs: Any) -> Any:
        """Get a single object matching the given criteria.

        Raises:
            DoesNotExist: No matching object found.
            MultipleObjectsReturned: More than one match.
        """
        # Fast path: direct ID lookup via API
        if "id" in kwargs and len(kwargs) == 1:
            try:
                raw = self._api().get_one(id=kwargs["id"])
                return self._wrap(raw)
            except prekit.ApiException as exc:
                if exc.status == 404:
                    raise DoesNotExist(f"No {self.model_class.__name__} with id={kwargs['id']!r}")
                raise

        results = self.filter(**kwargs)

        if len(results) == 0:
            criteria = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            raise DoesNotExist(f"No {self.model_class.__name__} matches {criteria}")
        if len(results) > 1:
            criteria = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            raise MultipleObjectsReturned(
                f"{len(results)} {self.model_class.__name__}s match {criteria}. "
                f"Use filter() to get all matches, or add more criteria to narrow down."
            )
        return results[0]

    def create(self, **kwargs: Any) -> Any:
        """Create a new object. Must be overridden by subclasses."""
        raise NotImplementedError(f"create() is not implemented for {type(self).__name__}")


class ElementManager(Manager):
    """Manager for SystemElement resources."""

    api_class_name = "SystemElementApi"
    model_class = Element

    def create(self, name: str, parent: Any = None, **kwargs: Any) -> Element:
        """Create a new system element.

        Args:
            name: Element name.
            parent: Parent element (Element, ID string, or None for root-level).
            **kwargs: Additional fields passed to SystemElementCreate.
        """
        now = "2000-01-01T00:00:00Z"
        data = {
            "name": name,
            "created_at": now,
            "updated_at": now,
            "normalized_name": "",
            "topic_context_section": "",
            "lft": 0,
            "rght": 0,
            "tree_id": 0,
            "level": 0,
            **kwargs,
        }
        if parent is not None:
            data["parent"] = resolve_id(parent)

        raw = self._api().post_one(data=prekit.SystemElementCreate(**data))
        return self._wrap(raw)


class SignalManager(Manager):
    """Manager for Signal resources."""

    api_class_name = "SignalApi"
    model_class = Signal

    def create(
        self,
        name: str,
        element: Any | None = None,
        data_type: str = "float",
        source: str = "connector",
        unit: str = "",
        **kwargs: Any,
    ) -> Signal:
        """Create a new signal.

        Args:
            name: Signal name.
            element: Parent system element (Element, ID string, or None).
            data_type: Data type (float, int, string, boolean).
            source: Signal source (connector, computation).
            unit: Unit of measurement.
            **kwargs: Additional fields passed to SignalCreate.
        """
        now = "2000-01-01T00:00:00Z"
        data = {
            "name": name,
            "source": source,
            "data_type": data_type,
            "unit": unit,
            "created_at": now,
            "updated_at": now,
            "normalized_name": "",
            "topic_context_section": "",
            **kwargs,
        }
        if element is not None:
            data["system_element"] = resolve_id(element)

        raw = self._api().post_one(data=prekit.SignalCreate(**data))
        return self._wrap(raw)


class TagManager(Manager):
    """Manager for DataTag resources."""

    api_class_name = "DataTagApi"
    model_class = Tag


class TagContextManager(Manager):
    """Manager for DataTagContext resources."""

    api_class_name = "DataTagContextApi"
    model_class = TagContext
