"""Tree browsing and ASCII printing for the PREKIT asset hierarchy.

Uses the SemanticHierarchyApi (lightweight) for tree data. Renders
compact or signal-expanded ASCII trees using box-drawing characters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class TreeNode:
    """A node in the asset tree (element or signal)."""

    def __init__(
        self,
        name: str,
        node_type: str = "element",
        node_id: str = "",
        data_type: str = "",
        unit: str = "",
        children: list[TreeNode] | None = None,
        signals: list[TreeNode] | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.name = name
        self.node_type = node_type  # "element" or "signal"
        self.node_id = node_id
        self.data_type = data_type
        self.unit = unit
        self.children = children or []
        self.signals = signals or []
        self.metadata = metadata or {}

    @property
    def signal_count(self) -> int:
        """Total signals on this node (direct only, not recursive)."""
        return len(self.signals)

    def total_signal_count(self) -> int:
        """Recursive signal count across the entire subtree."""
        count = len(self.signals)
        for child in self.children:
            count += child.total_signal_count()
        return count

    def collect_signal_ids(self) -> list[str]:
        """Collect all signal IDs in this subtree."""
        ids: list[str] = []
        for sig in self.signals:
            if sig.node_id:
                ids.append(sig.node_id)
        for child in self.children:
            ids.extend(child.collect_signal_ids())
        return ids


class Tree:
    """Represents a PREKIT asset hierarchy with ASCII printing."""

    def __init__(self, root: TreeNode) -> None:
        self.root = root

    def print(self, signals: bool = False) -> None:
        """Print the tree as ASCII art.

        Args:
            signals: If True, show signals as leaf nodes. If False (default),
                     show signal counts in brackets.
        """
        lines = _render_tree(self.root, signals=signals)
        print("\n".join(lines))

    def __str__(self) -> str:
        return "\n".join(_render_tree(self.root, signals=False))

    def to_string(self, signals: bool = False) -> str:
        """Return the tree as a string (for testing)."""
        return "\n".join(_render_tree(self.root, signals=signals))

    def flatten(self) -> list[TreeNode]:
        """Flatten the tree into a list of all nodes (depth-first)."""
        result: list[TreeNode] = []
        _flatten(self.root, result)
        return result

    def find(self, name: str) -> TreeNode | None:
        """Find the first element node with the given name."""
        for node in self.flatten():
            if node.name == name and node.node_type == "element":
                return node
        # Fallback: search signals too
        for node in self.flatten():
            if node.name == name:
                return node
        return None

    def find_by_path(self, *path: str) -> TreeNode | None:
        """Walk the hierarchy by exact child names.

        Example: tree.find_by_path("Brennöfen", "Brennofen Klein", "Sintern")
        """
        node = self.root
        for segment in path:
            match = None
            for child in node.children:
                if child.name == segment:
                    match = child
                    break
            if match is None:
                return None
            node = match
        return node

    def print_signals(self, element: str | TreeNode | None = None) -> None:
        """Print signals in a subtree with their units.

        Args:
            element: Element name, TreeNode, or None for the full tree.
        """
        if element is None:
            node = self.root
        elif isinstance(element, str):
            node = self.find(element)
            if node is None:
                print(f"Element '{element}' not found")
                return
        else:
            node = element
        _print_signals_tree(node, depth=0)

    def resolve_signals(self, element: str | TreeNode, signal_names: list[str]) -> dict[str, str]:
        """Find signal IDs by name within a subtree. Returns {name: id}."""
        if isinstance(element, str):
            node = self.find(element)
            if node is None:
                raise ValueError(f"Element '{element}' not found")
        else:
            node = element
        result: dict[str, str] = {}
        _find_signals_by_name(node, set(signal_names), result)
        return result


def _flatten(node: TreeNode, result: list[TreeNode]) -> None:
    result.append(node)
    for child in node.children:
        _flatten(child, result)
    for sig in node.signals:
        result.append(sig)


def _print_signals_tree(node: TreeNode, depth: int) -> None:
    """Print signals within a subtree, grouped by element."""
    indent = "  " * depth
    if node.node_type == "signal":
        unit = node.metadata.get("unit", node.unit) if node.metadata else node.unit
        unit_str = f"  [{unit}]" if unit else ""
        print(f"{indent}{node.name}{unit_str}")
        return
    has_content = node.signals or node.children
    label = f"{node.name}/" if has_content else node.name
    print(f"{indent}{label}")
    for child in node.children:
        _print_signals_tree(child, depth + 1)
    for sig in node.signals:
        _print_signals_tree(sig, depth + 1)


def _find_signals_by_name(node: TreeNode, names: set[str], result: dict[str, str]) -> None:
    """Recursively find signals by name and collect their IDs."""
    for sig in node.signals:
        if sig.name in names and sig.node_id:
            result[sig.name] = sig.node_id
    for child in node.children:
        _find_signals_by_name(child, names, result)


def _render_tree(node: TreeNode, signals: bool = False, prefix: str = "", is_last: bool = True, is_root: bool = True) -> list[str]:
    """Recursively render a tree node and its children as ASCII lines."""
    lines: list[str] = []

    # Root node
    if is_root:
        label = node.name
        if not signals and node.signal_count > 0:
            label += f" [{node.signal_count} signal{'s' if node.signal_count != 1 else ''}]"
        lines.append(label)
    else:
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        label = node.name
        if node.node_type == "signal":
            # Signals use single dash
            connector = "\u2514\u2500 " if is_last else "\u251c\u2500 "
            type_info = node.data_type
            if node.unit:
                type_info += f", {node.unit}"
            label += f" ({type_info})" if type_info else ""
        elif not signals and node.signal_count > 0:
            label += f" [{node.signal_count} signal{'s' if node.signal_count != 1 else ''}]"
        lines.append(f"{prefix}{connector}{label}")

    # Determine items to render below this node
    child_items: list[tuple[TreeNode, str]] = [(c, "element") for c in node.children]
    if signals:
        child_items.extend((s, "signal") for s in node.signals)

    for i, (child, kind) in enumerate(child_items):
        is_child_last = (i == len(child_items) - 1)
        if is_root:
            child_prefix = ""
        else:
            child_prefix = prefix + ("    " if is_last else "\u2502   ")

        child_lines = _render_tree(child, signals=signals, prefix=child_prefix, is_last=is_child_last, is_root=False)
        lines.extend(child_lines)

    return lines


def build_tree_from_api(client: Any, root: Any = None) -> Tree:
    """Fetch the asset tree from the API and build a Tree.

    Uses the simple-tree endpoint via raw HTTP to avoid Pydantic validation
    errors when the generated client's enums are out of date with the server.

    Args:
        client: Prekit client instance.
        root: Optional root element (Element, ID, or None for full tree).
    """
    import json

    from .helpers import resolve_id

    # Build the URL with optional query params
    path = "/api/v1/system-elements/simple-tree/"
    query_parts: list[str] = []
    if root is not None:
        query_parts.append(f"root_system_element_id={resolve_id(root)}")
    if query_parts:
        path += "?" + "&".join(query_parts)

    try:
        # Make a raw HTTP request via the REST client's pool manager to bypass
        # Pydantic deserialization (which can fail if the generated client's
        # enums are out of date with the server).
        config = client.api.configuration
        base_url = config.host.rstrip("/")
        full_url = f"{base_url}{path}"

        # Build auth headers
        req_headers: dict[str, str] = {"Accept": "application/json"}
        if config.access_token:
            req_headers["Authorization"] = f"Bearer {config.access_token}"
        api_key_dict = getattr(config, "api_key", None)
        if api_key_dict and isinstance(api_key_dict, dict):
            key_val = api_key_dict.get("ApiKeyAuth")
            if key_val:
                req_headers["X-API-Key"] = key_val

        pool = client.api.rest_client.pool_manager
        response = pool.request("GET", full_url, headers=req_headers, timeout=30)

        if response.status == 200 and response.data:
            raw_data = response.data.decode() if isinstance(response.data, bytes) else response.data
            data = json.loads(raw_data)
            tree_node = _parse_simple_tree_dict(data)
            return Tree(tree_node)
    except Exception:
        pass

    # Fallback: try the generated SemanticHierarchyApi (works if enums are up to date)
    try:
        import prekit_edge_node_api as prekit

        kwargs: dict[str, Any] = {}
        if root is not None:
            kwargs["root_system_element_id"] = resolve_id(root)
        api = prekit.SemanticHierarchyApi(api_client=client.api)
        raw_tree = api.get_one(**kwargs)
        tree_node = _parse_simple_tree(raw_tree)
        return Tree(tree_node)
    except Exception as e:
        return Tree(TreeNode(name=f"(error: {e})", node_type="element"))


def _parse_simple_tree_dict(data: dict) -> TreeNode:
    """Parse a simple-tree JSON dict (from raw HTTP response) into TreeNode."""
    children_raw = data.get("children", []) or []

    element_children: list[TreeNode] = []
    signal_children: list[TreeNode] = []

    for child in children_raw:
        child_type = child.get("type", "system_element")
        if child_type == "signal":
            child_meta = child.get("metadata", {}) or {}
            signal_children.append(TreeNode(
                name=child.get("name", ""),
                node_type="signal",
                node_id=child.get("id", ""),
                data_type=child.get("data_type", ""),
                unit=child_meta.get("unit", child.get("unit", "")),
                metadata=child_meta,
            ))
        elif child_type in ("system_element", None, ""):
            element_children.append(_parse_simple_tree_dict(child))

    return TreeNode(
        name=data.get("name", ""),
        node_type="element",
        node_id=data.get("id", ""),
        children=element_children,
        signals=signal_children,
        metadata=data.get("metadata", {}) or {},
    )


def _parse_simple_tree(node: Any) -> TreeNode:
    """Parse a SimpleSystemElementTree response into TreeNode."""
    children_raw = getattr(node, "children", []) or []

    element_children: list[TreeNode] = []
    signal_children: list[TreeNode] = []

    for child in children_raw:
        child_type = getattr(child, "type", "system_element")
        if child_type == "signal":
            signal_children.append(TreeNode(
                name=getattr(child, "name", ""),
                node_type="signal",
                node_id=getattr(child, "id", ""),
                data_type=getattr(child, "data_type", ""),
                unit=getattr(child, "unit", ""),
            ))
        elif child_type in ("system_element", None, ""):
            element_children.append(_parse_simple_tree(child))
        # Skip resources and annotation_types in tree display

    return TreeNode(
        name=getattr(node, "name", ""),
        node_type="element",
        node_id=getattr(node, "id", ""),
        children=element_children,
        signals=signal_children,
    )


def _parse_full_tree(node: Any) -> TreeNode:
    """Parse a SystemElementTree response into TreeNode."""
    data = getattr(node, "data", None)
    children_raw = getattr(node, "children", []) or []
    node_type = getattr(node, "type", "system_element")

    if node_type == "signal" and data:
        return TreeNode(
            name=getattr(data, "name", getattr(node, "label", "")),
            node_type="signal",
            node_id=getattr(data, "id", ""),
            data_type=getattr(data, "data_type", ""),
            unit=getattr(data, "unit", ""),
        )

    element_children: list[TreeNode] = []
    signal_children: list[TreeNode] = []

    for child in children_raw:
        child_type = getattr(child, "type", "system_element")
        parsed = _parse_full_tree(child)
        if child_type == "signal":
            signal_children.append(parsed)
        elif child_type == "system_element":
            element_children.append(parsed)

    name = ""
    if data:
        name = getattr(data, "name", "")
    if not name:
        name = getattr(node, "label", "")

    return TreeNode(
        name=name,
        node_type="element",
        node_id=getattr(data, "id", "") if data else "",
        children=element_children,
        signals=signal_children,
    )
