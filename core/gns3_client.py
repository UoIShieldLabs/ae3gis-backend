"""Thin client for interacting with the GNS3 REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping

import requests


class GNS3APIError(Exception):
    """Error from GNS3 API with detailed message."""
    def __init__(self, message: str, status_code: int, url: str, response_body: str | None = None):
        self.status_code = status_code
        self.url = url
        self.response_body = response_body
        super().__init__(message)


@dataclass(slots=True)
class GNS3Client:
    """Wrap an HTTP session with helpers for common GNS3 operations."""

    base_url: str
    session: requests.Session

    def _handle_response(self, response: requests.Response, context: str = "") -> Any:
        """Handle response and raise detailed error if failed."""
        if not response.ok:
            # Try to extract error message from GNS3 response
            error_detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    error_detail = body.get("message") or body.get("error") or body.get("detail") or ""
            except (ValueError, KeyError):
                error_detail = response.text[:500] if response.text else ""
            
            context_str = f" ({context})" if context else ""
            message = f"GNS3 API error{context_str}: {response.status_code} {response.reason}"
            if error_detail:
                message += f" - {error_detail}"
            
            raise GNS3APIError(message, response.status_code, str(response.url), error_detail)
        
        if response.text:
            try:
                return response.json()
            except ValueError:
                return response.text
        return {}

    def get(self, path: str) -> Any:
        response = self.session.get(self._url(path))
        return self._handle_response(response, f"GET {path}")

    def post(self, path: str, *, json: Mapping[str, Any] | None = None) -> Any:
        response = self.session.post(self._url(path), json=json or {})
        return self._handle_response(response, f"POST {path}")

    def list_projects(self) -> list[MutableMapping[str, Any]]:
        return list(self.get("/v2/projects"))

    def find_project_id(self, project_name: str) -> str:
        for project in self.list_projects():
            if project.get("name") == project_name:
                return project["project_id"]
        raise LookupError(f"Project named '{project_name}' not found")

    def add_node_from_template(
        self,
        project_id: str,
        template_id: str,
        name: str,
        x: int,
        y: int,
    ) -> MutableMapping[str, Any]:
        payload = {"x": x, "y": y, "name": name}
        node = self.post(f"/v2/projects/{project_id}/templates/{template_id}", json=payload)
        if not isinstance(node, Mapping) or "node_id" not in node:
            raise RuntimeError(f"Failed to create node '{name}': {node}")
        return dict(node)

    def get_node(self, project_id: str, node_id: str) -> MutableMapping[str, Any]:
        node = self.get(f"/v2/projects/{project_id}/nodes/{node_id}")
        return dict(node)

    def create_link(
        self,
        project_id: str,
        node_a: Mapping[str, Any],
        node_b: Mapping[str, Any],
    ) -> MutableMapping[str, Any]:
        payload = {"nodes": [dict(node_a), dict(node_b)]}
        link = self.post(f"/v2/projects/{project_id}/links", json=payload)
        return dict(link)

    def start_node(self, project_id: str, node_id: str) -> bool:
        try:
            self.post(f"/v2/projects/{project_id}/nodes/{node_id}/start")
            return True
        except (requests.HTTPError, GNS3APIError):
            return False

    def list_project_links(self, project_id: str) -> list[MutableMapping[str, Any]]:
        links = self.get(f"/v2/projects/{project_id}/links")
        return list(links)

    def list_templates(self) -> Iterable[MutableMapping[str, Any]]:
        templates = self.get("/v2/templates")
        for template in templates:
            yield dict(template)

    # -------------------------------------------------------------------------
    # DELETE operations
    # -------------------------------------------------------------------------

    def delete(self, path: str) -> bool:
        """Perform a DELETE request. Returns True on success."""
        response = self.session.delete(self._url(path))
        self._handle_response(response, f"DELETE {path}")
        return True

    def list_nodes(self, project_id: str) -> list[MutableMapping[str, Any]]:
        """List all nodes in a project."""
        nodes = self.get(f"/v2/projects/{project_id}/nodes")
        return list(nodes)

    def stop_all_nodes(self, project_id: str) -> bool:
        """Stop all nodes in a project."""
        try:
            self.post(f"/v2/projects/{project_id}/nodes/stop")
            return True
        except (requests.HTTPError, GNS3APIError):
            return False

    def delete_node(self, project_id: str, node_id: str) -> bool:
        """Delete a single node."""
        try:
            self.delete(f"/v2/projects/{project_id}/nodes/{node_id}")
            return True
        except (requests.HTTPError, GNS3APIError):
            return False

    def delete_link(self, project_id: str, link_id: str) -> bool:
        """Delete a single link."""
        try:
            self.delete(f"/v2/projects/{project_id}/links/{link_id}")
            return True
        except (requests.HTTPError, GNS3APIError):
            return False

    def delete_all_nodes(self, project_id: str) -> tuple[int, int, list[str]]:
        """
        Stop and delete all nodes and links in a project.
        
        Returns (nodes_deleted, links_deleted, errors).
        """
        errors: list[str] = []
        nodes_deleted = 0
        links_deleted = 0

        # Stop all nodes first
        self.stop_all_nodes(project_id)

        # Delete all links
        try:
            links = self.list_project_links(project_id)
            for link in links:
                link_id = link.get("link_id")
                if link_id and self.delete_link(project_id, link_id):
                    links_deleted += 1
        except (requests.HTTPError, GNS3APIError) as exc:
            errors.append(f"Failed to list/delete links: {exc}")

        # Delete all nodes
        try:
            nodes = self.list_nodes(project_id)
            for node in nodes:
                node_id = node.get("node_id")
                if node_id and self.delete_node(project_id, node_id):
                    nodes_deleted += 1
        except (requests.HTTPError, GNS3APIError) as exc:
            errors.append(f"Failed to list/delete nodes: {exc}")

        return nodes_deleted, links_deleted, errors

        return nodes_deleted, links_deleted, errors

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"
