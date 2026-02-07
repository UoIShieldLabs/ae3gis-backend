"""Scenario building logic, extracted from the legacy CLI script."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from .gns3_client import GNS3Client

NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _alias_base(name: str) -> str:
    return NON_ALNUM.sub("_", name).strip("_").upper()


def alias_variants(name: str) -> set[str]:
    base = _alias_base(name)
    variants = {f"NODE_{base}"}
    if "OPENVSWITCH" in base:
        variants.add(f"NODE_{base.replace('OPENVSWITCH', 'OVS')}")
    if "FIREWALL" in base:
        variants.add("NODE_FIREWALL")
    if base.startswith("IPTABLES_"):
        variants.add(f"NODE_{base.replace('IPTABLES_', '')}")
    return variants


def resolve_endpoint(
    ref: str,
    name_to_id: Mapping[str, str],
    alias_to_id: Mapping[str, str],
) -> str:
    if ref.upper().startswith("NODE_"):
        try:
            return alias_to_id[ref]
        except KeyError as exc:  # pragma: no cover - should raise for clarity
            raise LookupError(f"Unresolved link placeholder '{ref}'") from exc
    if ref in name_to_id:
        return name_to_id[ref]
    if ref.count("-") >= 4:
        return ref
    raise LookupError(f"Unresolved link endpoint '{ref}'")


@dataclass(slots=True)
class ScenarioBuildResult:
    """Artifacts produced when a scenario is built."""

    project_id: str
    project_name: str | None
    nodes_created: list[MutableMapping[str, Any]]
    links_created: list[MutableMapping[str, Any]]
    nodes_detail: list[MutableMapping[str, Any]]
    links_detail: list[MutableMapping[str, Any]]
    config_record: MutableMapping[str, Any]
    warnings: list[str]


class ScenarioBuilder:
    """Create nodes/links in GNS3 according to a scenario specification."""

    def __init__(self, client: GNS3Client, *, request_delay: float = 0.0) -> None:
        self._client = client
        self._request_delay = max(0.0, request_delay)

    def build(
        self,
        scenario: Mapping[str, Any],
        *,
        start_nodes: bool = False,
    ) -> ScenarioBuildResult:
        project_id, project_name = self._resolve_project(scenario)
        nodes_spec = scenario.get("nodes", []) or []
        if not isinstance(nodes_spec, Sequence) or not nodes_spec:
            raise ValueError("Scenario must include a non-empty 'nodes' array")

        templates_map = scenario.get("templates", {}) or {}

        created_nodes: list[MutableMapping[str, Any]] = []
        name_to_id: dict[str, str] = {}
        alias_to_id: dict[str, str] = {}

        for spec in nodes_spec:
            node = self._create_node(project_id, spec, templates_map)
            created_nodes.append(node)
            name = node.get("name", "")
            node_id = node.get("node_id", "")
            if isinstance(name, str) and isinstance(node_id, str):
                name_to_id[name] = node_id
                for alias in alias_variants(name):
                    alias_to_id.setdefault(alias, node_id)

            if self._request_delay:
                time.sleep(self._request_delay)

        links_spec = scenario.get("links", []) or []
        created_links = self._create_links(project_id, links_spec, name_to_id, alias_to_id)

        if start_nodes:
            for node in created_nodes:
                node_id = node.get("node_id")
                if isinstance(node_id, str):
                    self._client.start_node(project_id, node_id)

        nodes_detail: list[MutableMapping[str, Any]] = []
        for node in created_nodes:
            node_id = node.get("node_id")
            if not isinstance(node_id, str):
                continue
            nodes_detail.append(self._client.get_node(project_id, node_id))
            if self._request_delay:
                time.sleep(self._request_delay)
        
        # Graceful degradation: if listing links fails, continue with empty list
        warnings: list[str] = []
        links_detail: list[MutableMapping[str, Any]] = []
        try:
            links_detail = list(self._client.list_project_links(project_id))
        except Exception as exc:
            warnings.append(f"Failed to fetch links detail: {exc}")

        config_record = make_config_record(project_name, project_id, nodes_detail, links_detail)

        return ScenarioBuildResult(
            project_id=project_id,
            project_name=project_name,
            nodes_created=created_nodes,
            links_created=created_links,
            nodes_detail=nodes_detail,
            links_detail=links_detail,
            config_record=config_record,
            warnings=warnings,
        )

    def _resolve_project(self, scenario: Mapping[str, Any]) -> tuple[str, str | None]:
        project_id = scenario.get("project_id")
        project_name = scenario.get("project_name")
        if project_id:
            return str(project_id), project_name
        if project_name:
            return self._client.find_project_id(project_name), str(project_name)
        raise ValueError("Scenario must include 'project_id' or 'project_name'")

    def _create_node(
        self,
        project_id: str,
        spec: Mapping[str, Any],
        templates_map: Mapping[str, str],
    ) -> MutableMapping[str, Any]:
        name = spec.get("name")
        if not name:
            raise ValueError("Scenario node entry missing 'name'")
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))

        template_id = spec.get("template_id")
        if not template_id:
            template_id = self._resolve_template_id(spec, templates_map)
        node = self._client.add_node_from_template(project_id, str(template_id), str(name), x, y)
        return node

    def _resolve_template_id(
        self,
        spec: Mapping[str, Any],
        templates_map: Mapping[str, str],
    ) -> str:
        t_key = spec.get("template_key")
        if t_key and t_key in templates_map:
            return str(templates_map[t_key])
        t_name = spec.get("template_name")
        if t_name:
            template_lookup = {
                template["name"]: template["template_id"] for template in self._client.list_templates()
            }
            if t_name not in template_lookup:
                raise LookupError(f"Template '{t_name}' not found on GNS3 server")
            return str(template_lookup[t_name])
        raise ValueError("Node spec requires template_id/template_key/template_name")

    def _create_links(
        self,
        project_id: str,
        links_spec: Iterable[Mapping[str, Any]],
        name_to_id: Mapping[str, str],
        alias_to_id: Mapping[str, str],
    ) -> list[MutableMapping[str, Any]]:
        created_links: list[MutableMapping[str, Any]] = []
        for index, link_spec in enumerate(links_spec, start=1):
            nodes = link_spec.get("nodes")
            if not isinstance(nodes, Sequence) or len(nodes) != 2:
                raise ValueError(f"Link #{index} must specify exactly two endpoints")
            a_in, b_in = nodes[0], nodes[1]
            a_ref = a_in.get("node_id") or a_in.get("name")
            b_ref = b_in.get("node_id") or b_in.get("name")
            if not isinstance(a_ref, str) or not isinstance(b_ref, str):
                raise ValueError(f"Link #{index} missing node references")
            a_id = resolve_endpoint(a_ref, name_to_id, alias_to_id)
            b_id = resolve_endpoint(b_ref, name_to_id, alias_to_id)
            node_a = {
                "node_id": a_id,
                "adapter_number": int(a_in.get("adapter_number", 0)),
                "port_number": int(a_in.get("port_number", 0)),
            }
            node_b = {
                "node_id": b_id,
                "adapter_number": int(b_in.get("adapter_number", 0)),
                "port_number": int(b_in.get("port_number", 0)),
            }
            created_links.append(self._client.create_link(project_id, node_a, node_b))
            if self._request_delay:
                time.sleep(self._request_delay)
        return created_links


def load_scenario(path: str | Path) -> Mapping[str, Any]:
    scenario_path = Path(path)
    if not scenario_path.exists():
        raise FileNotFoundError(scenario_path)
    with scenario_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError("Scenario JSON must contain an object")
    return data


def make_config_record(
    project_name: str | None,
    project_id: str,
    nodes_detail: Sequence[Mapping[str, Any]],
    links_detail: Sequence[Mapping[str, Any]],
) -> MutableMapping[str, Any]:
    config: MutableMapping[str, Any] = {
        "project_name": project_name or "",
        "project_id": project_id,
        "nodes": [],
        "links": [],
    }

    for node in nodes_detail:
        properties = node.get("properties") or {}
        record = {
            "name": node.get("name"),
            "node_id": node.get("node_id"),
            "template_id": node.get("template_id"),
            "compute_id": node.get("compute_id", "local"),
            "console": node.get("console"),
            "console_host": node.get("console_host"),
            "console_type": node.get("console_type"),
            "ports": [
                {
                    "adapter_number": port.get("adapter_number", 0),
                    "port_number": port.get("port_number", 0),
                }
                for port in (node.get("ports") or [])
            ],
            "properties": {
                "adapters": properties.get("adapters"),
                "aux": properties.get("aux"),
            },
            "status": node.get("status"),
            "x": node.get("x", 0),
            "y": node.get("y", 0),
        }
        config["nodes"].append(record)

    for link in links_detail:
        config["links"].append(
            {
                "link_id": link.get("link_id"),
                "link_type": link.get("link_type", "ethernet"),
                "nodes": [
                    {
                        "node_id": n.get("node_id"),
                        "adapter_number": n.get("adapter_number", 0),
                        "port_number": n.get("port_number", 0),
                    }
                    for n in link.get("nodes", [])
                ],
            }
        )

    return config
