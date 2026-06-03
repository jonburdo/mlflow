from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from mlflow.entities.mcp_server import MCPStatus, MCPTool
from mlflow.exceptions import MlflowException
from mlflow.server.mcp_server_api import mcp_server_router
from mlflow.store.tracking.mcp_server_registry.abstract_mixin import MCPServerRegistryMixin
from mlflow.store.tracking.mcp_server_registry.rest_mixin import RestMCPServerRegistryMixin
from mlflow.store.tracking.mcp_server_registry.sqlalchemy_mixin import (
    SqlAlchemyMCPServerRegistryMixin,
)
from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore
from mlflow.utils.rest_utils import MlflowHostCreds


def _server_json(name: str, version: str, **extra) -> dict[str, Any]:
    d = {"name": name, "version": version}
    d.update(extra)
    return d


class _TestRestClient(RestMCPServerRegistryMixin):
    """Minimal class that provides get_host_creds for the mixin."""

    def __init__(self, test_client: TestClient):
        self._test_client = test_client

    def get_host_creds(self):
        return MlflowHostCreds(host="http://testserver")


@pytest.fixture
def store(tmp_path: Path):
    artifact_uri = tmp_path / "artifacts"
    artifact_uri.mkdir()
    return SqlAlchemyStore(f"sqlite:///{tmp_path / 'test.db'}", artifact_uri.as_uri())


@pytest.fixture
def rest_client(store):
    app = FastAPI()
    app.include_router(mcp_server_router)
    test_client = TestClient(app)
    client = _TestRestClient(test_client)
    with (
        mock.patch(
            "mlflow.server.handlers._get_tracking_store",
            return_value=store,
        ),
        mock.patch(
            "mlflow.store.tracking.mcp_server_registry.rest_mixin.http_request",
            side_effect=lambda host_creds, endpoint, method, **kwargs: _route_to_test_client(
                test_client, endpoint, method, **kwargs
            ),
        ),
    ):
        yield client


def _route_to_test_client(test_client: TestClient, endpoint: str, method: str, **kwargs):
    method = method.upper()
    if method == "GET":
        return test_client.get(endpoint, params=kwargs.get("params"))
    elif method == "POST":
        return test_client.post(endpoint, json=kwargs.get("json"))
    elif method == "PATCH":
        return test_client.patch(endpoint, json=kwargs.get("json"))
    elif method == "DELETE":
        return test_client.delete(endpoint)
    raise ValueError(f"Unsupported method: {method}")


def test_mcp_registry_mixin_signatures_match_exactly():
    methods = [
        name
        for name, value in MCPServerRegistryMixin.__dict__.items()
        if callable(value) and not name.startswith("_")
    ]
    for method_name in methods:
        abstract_sig = inspect.signature(getattr(MCPServerRegistryMixin, method_name))
        sqlalchemy_sig = inspect.signature(getattr(SqlAlchemyMCPServerRegistryMixin, method_name))
        rest_sig = inspect.signature(getattr(RestMCPServerRegistryMixin, method_name))
        assert sqlalchemy_sig == abstract_sig, method_name
        assert rest_sig == abstract_sig, method_name


def test_rest_client_url_encodes_slashed_name_and_version():
    client = _TestRestClient(TestClient(FastAPI()))
    response = mock.Mock(status_code=200, text="ok")
    response.json.return_value = {
        "name": "io.github.user/my-server",
        "version": "2025/06",
        "server_json": {"name": "io.github.user/my-server", "version": "2025/06"},
        "status": "draft",
        "aliases": [],
        "tags": {},
    }
    with mock.patch(
        "mlflow.store.tracking.mcp_server_registry.rest_mixin.http_request",
        return_value=response,
    ) as http_request_mock:
        client.get_mcp_server_version("io.github.user/my-server", "2025/06")

    assert (
        http_request_mock.call_args.kwargs["endpoint"]
        == "/ajax-api/3.0/mlflow/mcp-servers/io.github.user%2Fmy-server/versions/2025%2F06"
    )


def test_create_and_get_server(rest_client):
    server = rest_client.create_mcp_server("my-server", description="A server")
    assert server.name == "my-server"
    assert server.description == "A server"
    assert server.creation_timestamp is not None

    fetched = rest_client.get_mcp_server("my-server")
    assert fetched.name == "my-server"
    assert fetched.description == "A server"


def test_create_and_get_server_with_slashed_name(rest_client):
    name = "io.github.user/my-server"
    rest_client.create_mcp_server(name, description="A server")
    fetched = rest_client.get_mcp_server(name)
    assert fetched.name == name
    assert fetched.description == "A server"


def test_search_servers_pagination(rest_client):
    for name in ["alpha", "beta", "gamma"]:
        rest_client.create_mcp_server(name)
    page1 = rest_client.search_mcp_servers(max_results=2)
    assert len(page1) == 2
    assert page1.token is not None

    page2 = rest_client.search_mcp_servers(max_results=2, page_token=page1.token)
    assert len(page2) == 1


def test_update_server(rest_client):
    rest_client.create_mcp_server("upd")
    updated = rest_client.update_mcp_server("upd", description="new desc", display_name="Upd")
    assert updated.description == "new desc"
    assert updated.display_name == "Upd"


def test_update_server_can_clear_nullable_fields(rest_client):
    rest_client.create_mcp_server("clear-srv", description="old")
    updated = rest_client.update_mcp_server("clear-srv", description=None)
    assert updated.description is None


def test_delete_server(rest_client):
    rest_client.create_mcp_server("del")
    rest_client.delete_mcp_server("del")
    with pytest.raises(MlflowException, match="not found") as exc_info:
        rest_client.get_mcp_server("del")
    assert exc_info.value.error_code == "RESOURCE_DOES_NOT_EXIST"


def test_create_duplicate_server_preserves_error_code(rest_client):
    rest_client.create_mcp_server("dup")
    with pytest.raises(MlflowException, match="already exists") as exc_info:
        rest_client.create_mcp_server("dup")
    assert exc_info.value.error_code == "RESOURCE_ALREADY_EXISTS"


def test_create_and_get_version(rest_client):
    sj = _server_json("v-srv", "1.0", title="Test")
    ver = rest_client.create_mcp_server_version(sj, status=MCPStatus.ACTIVE)
    assert ver.name == "v-srv"
    assert ver.version == "1.0"
    assert ver.status == MCPStatus.ACTIVE

    fetched = rest_client.get_mcp_server_version("v-srv", "1.0")
    assert fetched.version == "1.0"
    assert fetched.server_json["title"] == "Test"


def test_create_and_get_version_with_slashed_name_and_version(rest_client):
    name = "io.github.user/versioned-server"
    version = "2025/06"
    ver = rest_client.create_mcp_server_version(
        _server_json(name, version), status=MCPStatus.ACTIVE
    )
    assert ver.name == name
    assert ver.version == version

    fetched = rest_client.get_mcp_server_version(name, version)
    assert fetched.version == version


def test_create_version_with_tools(rest_client):
    sj = _server_json("tools-srv", "1.0")
    tools = [MCPTool(name="search", description="Search the web")]
    ver = rest_client.create_mcp_server_version(sj, status=MCPStatus.ACTIVE, tools=tools)
    assert len(ver.tools) == 1
    assert ver.tools[0].name == "search"


def test_create_version_preserves_empty_tools_list(rest_client):
    sj = _server_json("empty-tools-srv", "1.0")
    ver = rest_client.create_mcp_server_version(sj, status=MCPStatus.ACTIVE, tools=[])
    assert ver.tools == []


def test_get_latest_version(rest_client):
    for v in ["1.0", "2.0"]:
        rest_client.create_mcp_server_version(_server_json("lat", v), status=MCPStatus.ACTIVE)
    latest = rest_client.get_latest_mcp_server_version("lat")
    assert latest.version == "2.0"


def test_version_named_latest_round_trips_via_version_route(rest_client):
    rest_client.create_mcp_server_version(
        _server_json("lat-literal", "latest"), status=MCPStatus.ACTIVE
    )
    rest_client.create_mcp_server_version(
        _server_json("lat-literal", "2.0"), status=MCPStatus.ACTIVE
    )
    rest_client.update_mcp_server("lat-literal", latest_version="2.0")

    version_named_latest = rest_client.get_mcp_server_version("lat-literal", "latest")
    computed_latest = rest_client.get_latest_mcp_server_version("lat-literal")

    assert version_named_latest.version == "latest"
    assert computed_latest.version == "2.0"


def test_search_versions(rest_client):
    for v in ["1.0", "2.0", "3.0"]:
        rest_client.create_mcp_server_version(_server_json("sv", v), status=MCPStatus.ACTIVE)
    results = rest_client.search_mcp_server_versions("sv", max_results=2)
    assert len(results) == 2
    assert results.token is not None


def test_update_version(rest_client):
    rest_client.create_mcp_server_version(_server_json("uv", "1.0"))
    updated = rest_client.update_mcp_server_version("uv", "1.0", status=MCPStatus.ACTIVE)
    assert updated.status == MCPStatus.ACTIVE


def test_update_version_can_clear_display_name(rest_client):
    rest_client.create_mcp_server_version(
        _server_json("uv-clear", "1.0"), display_name="v1", status=MCPStatus.ACTIVE
    )
    updated = rest_client.update_mcp_server_version("uv-clear", "1.0", display_name=None)
    assert updated.display_name is None


def test_update_version_preserves_empty_tools_list(rest_client):
    rest_client.create_mcp_server_version(
        _server_json("uv-empty-tools", "1.0"),
        status=MCPStatus.ACTIVE,
        tools=[MCPTool(name="search", description="Search the web")],
    )
    updated = rest_client.update_mcp_server_version("uv-empty-tools", "1.0", tools=[])
    assert updated.tools == []


def test_delete_version(rest_client):
    rest_client.create_mcp_server_version(_server_json("dv", "1.0"))
    rest_client.delete_mcp_server_version("dv", "1.0")


def test_create_version_missing_name_raises_mlflow_exception(rest_client):
    with pytest.raises(MlflowException, match="must contain 'name' and 'version' keys") as exc_info:
        rest_client.create_mcp_server_version({"version": "1.0"})
    assert exc_info.value.error_code == "INVALID_PARAMETER_VALUE"


def test_create_and_get_binding(rest_client):
    rest_client.create_mcp_server_version(_server_json("b-srv", "1.0"), status=MCPStatus.ACTIVE)
    binding = rest_client.create_mcp_access_binding(
        server_name="b-srv",
        endpoint_url="https://mcp.example.com",
        server_version="1.0",
    )
    assert binding.server_name == "b-srv"
    assert binding.endpoint_url == "https://mcp.example.com"

    fetched = rest_client.get_mcp_access_binding("b-srv", binding.binding_id)
    assert fetched.endpoint_url == "https://mcp.example.com"


def test_get_binding_includes_resolved_version(rest_client):
    rest_client.create_mcp_server_version(_server_json("brv", "1.0"), status=MCPStatus.ACTIVE)
    binding = rest_client.create_mcp_access_binding(
        server_name="brv",
        endpoint_url="https://mcp.example.com/brv",
        server_version="1.0",
    )
    fetched = rest_client.get_mcp_access_binding("brv", binding.binding_id)
    assert fetched.resolved_version is not None
    assert fetched.resolved_version.name == "brv"
    assert fetched.resolved_version.version == "1.0"


def test_search_bindings_workspace_wide(rest_client):
    for name in ["ws-a", "ws-b"]:
        rest_client.create_mcp_server_version(_server_json(name, "1.0"), status=MCPStatus.ACTIVE)
        rest_client.create_mcp_access_binding(
            server_name=name,
            endpoint_url=f"https://mcp.example.com/{name}",
            server_version="1.0",
        )
    results = rest_client.search_mcp_access_bindings()
    assert len(results) == 2


def test_search_bindings_include_resolved_version_via_alias(rest_client):
    rest_client.create_mcp_server_version(_server_json("sbra", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.set_mcp_server_alias("sbra", "prod", "1.0")
    rest_client.create_mcp_access_binding(
        server_name="sbra",
        endpoint_url="https://mcp.example.com/sbra",
        server_alias="prod",
    )
    results = rest_client.search_mcp_access_bindings(server_name="sbra")
    assert len(results) == 1
    assert results[0].resolved_version is not None
    assert results[0].resolved_version.version == "1.0"


def test_search_bindings_server_scoped(rest_client):
    for name in ["sc-a", "sc-b"]:
        rest_client.create_mcp_server_version(_server_json(name, "1.0"), status=MCPStatus.ACTIVE)
        rest_client.create_mcp_access_binding(
            server_name=name,
            endpoint_url=f"https://mcp.example.com/{name}",
            server_version="1.0",
        )
    results = rest_client.search_mcp_access_bindings(server_name="sc-a")
    assert len(results) == 1
    assert results[0].server_name == "sc-a"


def test_update_binding(rest_client):
    rest_client.create_mcp_server_version(_server_json("ub", "1.0"), status=MCPStatus.ACTIVE)
    binding = rest_client.create_mcp_access_binding(
        server_name="ub",
        endpoint_url="https://old.example.com",
        server_version="1.0",
    )
    updated = rest_client.update_mcp_access_binding(
        server_name="ub",
        binding_id=binding.binding_id,
        endpoint_url="https://new.example.com",
    )
    assert updated.endpoint_url == "https://new.example.com"


def test_delete_binding(rest_client):
    rest_client.create_mcp_server_version(_server_json("db", "1.0"), status=MCPStatus.ACTIVE)
    binding = rest_client.create_mcp_access_binding(
        server_name="db",
        endpoint_url="https://mcp.example.com",
        server_version="1.0",
    )
    rest_client.delete_mcp_access_binding("db", binding.binding_id)
    with pytest.raises(MlflowException, match="not found"):
        rest_client.get_mcp_access_binding("db", binding.binding_id)


def test_server_tags(rest_client):
    rest_client.create_mcp_server("tag-srv")
    rest_client.set_mcp_server_tag("tag-srv", "env", "prod")
    server = rest_client.get_mcp_server("tag-srv")
    assert server.tags["env"] == "prod"

    rest_client.delete_mcp_server_tag("tag-srv", "env")
    server = rest_client.get_mcp_server("tag-srv")
    assert "env" not in server.tags


def test_server_tag_with_slash_key(rest_client):
    rest_client.create_mcp_server("slash-tag-srv")
    rest_client.set_mcp_server_tag("slash-tag-srv", "team/platform", "prod")
    server = rest_client.get_mcp_server("slash-tag-srv")
    assert server.tags["team/platform"] == "prod"

    rest_client.delete_mcp_server_tag("slash-tag-srv", "team/platform")
    server = rest_client.get_mcp_server("slash-tag-srv")
    assert "team/platform" not in server.tags


def test_version_tags(rest_client):
    rest_client.create_mcp_server_version(_server_json("vt", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.set_mcp_server_version_tag("vt", "1.0", "stage", "beta")
    ver = rest_client.get_mcp_server_version("vt", "1.0")
    assert ver.tags["stage"] == "beta"

    rest_client.delete_mcp_server_version_tag("vt", "1.0", "stage")
    ver = rest_client.get_mcp_server_version("vt", "1.0")
    assert "stage" not in ver.tags


def test_version_tag_with_slash_key(rest_client):
    rest_client.create_mcp_server_version(_server_json("slash-vt", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.set_mcp_server_version_tag("slash-vt", "1.0", "team/platform", "beta")
    ver = rest_client.get_mcp_server_version("slash-vt", "1.0")
    assert ver.tags["team/platform"] == "beta"

    rest_client.delete_mcp_server_version_tag("slash-vt", "1.0", "team/platform")
    ver = rest_client.get_mcp_server_version("slash-vt", "1.0")
    assert "team/platform" not in ver.tags


def test_set_and_resolve_alias(rest_client):
    rest_client.create_mcp_server_version(_server_json("alias-srv", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.set_mcp_server_alias("alias-srv", "prod", "1.0")
    ver = rest_client.get_mcp_server_version_by_alias("alias-srv", "prod")
    assert ver.version == "1.0"


def test_alias_with_slash_round_trips(rest_client):
    rest_client.create_mcp_server_version(
        _server_json("slash-alias", "1.0"), status=MCPStatus.ACTIVE
    )
    rest_client.set_mcp_server_alias("slash-alias", "team/prod", "1.0")
    ver = rest_client.get_mcp_server_version_by_alias("slash-alias", "team/prod")
    assert ver.version == "1.0"
    rest_client.delete_mcp_server_alias("slash-alias", "team/prod")
    with pytest.raises(MlflowException, match="not found"):
        rest_client.get_mcp_server_version_by_alias("slash-alias", "team/prod")


def test_delete_alias(rest_client):
    rest_client.create_mcp_server_version(_server_json("da", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.set_mcp_server_alias("da", "staging", "1.0")
    rest_client.delete_mcp_server_alias("da", "staging")


def test_server_aliases_dict_format(rest_client):
    rest_client.create_mcp_server_version(_server_json("rt", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.set_mcp_server_alias("rt", "prod", "1.0")
    server = rest_client.get_mcp_server("rt")
    assert isinstance(server.aliases, dict)
    assert server.aliases["prod"] == "1.0"


def test_server_access_bindings_include_resolved_version(rest_client):
    rest_client.create_mcp_server_version(_server_json("srv-bind", "1.0"), status=MCPStatus.ACTIVE)
    rest_client.create_mcp_access_binding(
        server_name="srv-bind",
        endpoint_url="https://mcp.example.com/srv-bind",
        server_version="1.0",
    )
    server = rest_client.get_mcp_server("srv-bind")
    assert len(server.access_bindings) == 1
    assert server.access_bindings[0].resolved_version is not None
    assert server.access_bindings[0].resolved_version.version == "1.0"


def test_server_json_extra_fields(rest_client):
    sj = _server_json("extra", "1.0", custom_field="hello")
    ver = rest_client.create_mcp_server_version(sj, status=MCPStatus.ACTIVE)
    assert ver.server_json["custom_field"] == "hello"


def test_server_json_explicit_nulls_preserved(rest_client):
    sj = _server_json("null-extra", "1.0", description=None, custom_field=None)
    ver = rest_client.create_mcp_server_version(sj, status=MCPStatus.ACTIVE)
    assert "description" in ver.server_json
    assert ver.server_json["description"] is None
    assert "custom_field" in ver.server_json
    assert ver.server_json["custom_field"] is None
    assert "repository" not in ver.server_json


def test_tools_round_trip(rest_client):
    sj = _server_json("tools-rt", "1.0")
    tools = [
        MCPTool(
            name="search",
            description="Search",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
    ]
    ver = rest_client.create_mcp_server_version(sj, status=MCPStatus.ACTIVE, tools=tools)
    assert ver.tools[0].input_schema == {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
