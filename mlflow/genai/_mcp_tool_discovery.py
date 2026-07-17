"""MCP tool discovery for registry version create.

Queries a live MCP server (via ``tools/list``) and maps results to
:class:`~mlflow.entities.mcp_server.MCPTool`. Requires the optional
``mlflow[mcp]`` extra (fastmcp).

Used when ``tools`` is omitted / ``NOT_SET`` on create (fluent SDK, store,
and REST), if ``MLFLOW_ENABLE_MCP_TOOL_DISCOVERY`` is enabled. Explicit
``None`` / ``[]`` / a list disables discovery.

Discovery is best-effort: failures (network, auth, timeout, missing extra,
or no eligible remote) leave ``tools`` as ``None`` and do not abort create.
Authenticated discovery headers are currently only available on the fluent
``register_mcp_server(..., mcp_server_access_headers=...)`` path.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Mapping

from mlflow.entities.mcp_server import MCPRemoteTransportType, MCPTool
from mlflow.environment_variables import MLFLOW_ENABLE_MCP_TOOL_DISCOVERY
from mlflow.exceptions import MlflowException
from mlflow.store.tracking.mcp_server_registry.abstract_mixin import NOT_SET
from mlflow.utils.validation import _validate_mcp_tool_discovery_url

# Bound create-time discovery so a hung remote cannot stall registration.
# On timeout, discovery is skipped and create continues with tools=None.
DEFAULT_MCP_TOOL_DISCOVER_TIMEOUT_SECONDS = 10.0
# Client HTTP timeouts are slightly looser so asyncio.wait_for owns the
# user-facing deadline and the clearer "Timed out discovering" error path.
_CLIENT_TIMEOUT_SLACK_SECONDS = 1.0

_logger = logging.getLogger(__name__)


def _run_coro_sync(coro: Any, timeout: float | None = None) -> Any:
    """Run an async coroutine from a synchronous caller.

    Falls back to a worker thread when an event loop is already running
    (e.g. Jupyter notebooks or async test runners), matching other MLflow
    sync-over-async helpers.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(thread_name_prefix="mcp_tool_discovery") as pool:
            future = pool.submit(asyncio.run, coro)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError as e:
                raise MlflowException.invalid_parameter_value(
                    f"Timed out discovering MCP tools after {timeout:g}s"
                    if timeout is not None
                    else "Timed out discovering MCP tools"
                ) from e
    return asyncio.run(coro)


def _require_fastmcp():
    try:
        from fastmcp import Client
        from fastmcp.client.transports import SSETransport, StreamableHttpTransport
    except ImportError as e:
        raise MlflowException.invalid_parameter_value(
            "MCP tool discovery requires the optional MCP dependencies. "
            "Install them with: pip install 'mlflow[mcp]'"
        ) from e
    return Client, StreamableHttpTransport, SSETransport


def _tool_from_sdk(tool: Any) -> MCPTool:
    if hasattr(tool, "model_dump"):
        data = tool.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(tool, dict):
        data = tool
    else:
        data = {
            "name": getattr(tool, "name", None),
            "title": getattr(tool, "title", None),
            "description": getattr(tool, "description", None),
            "inputSchema": getattr(tool, "inputSchema", None)
            or getattr(tool, "input_schema", None),
            "outputSchema": getattr(tool, "outputSchema", None)
            or getattr(tool, "output_schema", None),
            "annotations": getattr(tool, "annotations", None),
            "icons": getattr(tool, "icons", None),
            "execution": getattr(tool, "execution", None),
        }
    # Drop MCP protocol-only fields that MCPTool does not model.
    data.pop("meta", None)
    return MCPTool.from_dict(data)


def _build_transport(
    url: str,
    transport_type: MCPRemoteTransportType,
    headers: Mapping[str, str] | None,
    StreamableHttpTransport,
    SSETransport,
):
    header_dict = dict(headers) if headers else None
    if transport_type == MCPRemoteTransportType.STREAMABLE_HTTP:
        return StreamableHttpTransport(url=url, headers=header_dict)
    if transport_type == MCPRemoteTransportType.SSE:
        return SSETransport(url=url, headers=header_dict)
    raise MlflowException.invalid_parameter_value(
        f"Unsupported MCP transport for tool discovery: {transport_type!r}"
    )


async def _alist_tools(
    url: str,
    transport_type: MCPRemoteTransportType,
    headers: Mapping[str, str] | None,
    timeout_seconds: float,
) -> list[MCPTool]:
    Client, StreamableHttpTransport, SSETransport = _require_fastmcp()
    transport = _build_transport(
        url, transport_type, headers, StreamableHttpTransport, SSETransport
    )
    # wait_for owns the advertised deadline; client budget is slightly larger
    # so a hung remote surfaces as "Timed out discovering" rather than a raw
    # client ReadTimeout.
    client_timeout = timeout_seconds + _CLIENT_TIMEOUT_SLACK_SECONDS

    async def _list() -> list[Any]:
        async with Client(
            transport,
            timeout=client_timeout,
            init_timeout=client_timeout,
        ) as client:
            return await client.list_tools()

    try:
        sdk_tools = await asyncio.wait_for(_list(), timeout=timeout_seconds)
    except asyncio.TimeoutError as e:
        # On 3.11+ asyncio.TimeoutError is an alias of TimeoutError; catch the
        # asyncio form so 3.10 also maps wait_for timeouts correctly.
        raise MlflowException.invalid_parameter_value(
            f"Timed out discovering MCP tools from {url!r} after {timeout_seconds:g}s"
        ) from e
    return [_tool_from_sdk(t) for t in sdk_tools]


def discover_mcp_tools(
    url: str,
    transport_type: MCPRemoteTransportType = MCPRemoteTransportType.STREAMABLE_HTTP,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_MCP_TOOL_DISCOVER_TIMEOUT_SECONDS,
) -> list[MCPTool]:
    """List tools from a deployed MCP server endpoint.

    Performs a one-shot ``tools/list`` scrape over the given remote transport.
    Used when create-time ``tools`` is omitted / ``NOT_SET``.

    Args:
        url: MCP server URL (streamable-http or SSE endpoint).
        transport_type: Remote transport type.
        headers: Optional HTTP headers for the discovery session (e.g. auth).
            Available tools may differ depending on these credentials.
        timeout: Overall deadline in seconds for connect + ``tools/list``.
            Defaults to ``DEFAULT_MCP_TOOL_DISCOVER_TIMEOUT_SECONDS``.

    Returns:
        Discovered :class:`~mlflow.entities.mcp_server.MCPTool` definitions.

    Raises:
        MlflowException: If the ``mlflow[mcp]`` extra is missing, discovery fails,
            or the timeout is exceeded. Callers that should not abort create
            (``resolve_tools_for_create``) catch and soft-fail to ``None``.
    """
    if timeout <= 0:
        raise MlflowException.invalid_parameter_value(f"timeout must be positive, got {timeout!r}")
    _validate_mcp_tool_discovery_url(url)
    try:
        return _run_coro_sync(
            _alist_tools(url, transport_type, headers, timeout),
            timeout=timeout + _CLIENT_TIMEOUT_SLACK_SECONDS,
        )
    except MlflowException:
        raise
    except Exception as e:
        raise MlflowException.invalid_parameter_value(
            f"Failed to discover MCP tools from {url!r}: {e}"
        ) from e


def _first_discovery_remote(
    server_json: dict[str, Any],
) -> tuple[str, MCPRemoteTransportType] | None:
    """Return the first remotes[] entry eligible for tool discovery.

    Skips entries with no URL and entries that fail discovery URL safety checks
    (scheme, embedded credentials, private/loopback hosts when disallowed).
    Malformed remotes (non-object entry, blank URL, unknown transport) still
    raise. Does not failover after a live scrape failure — only selection skips
    ineligible URLs.
    """
    remotes = server_json.get("remotes") or []
    if not isinstance(remotes, list):
        raise MlflowException.invalid_parameter_value(
            "Invalid server_json.remotes. Expected a list of remote objects."
        )

    for remote in remotes:
        if not isinstance(remote, dict):
            raise MlflowException.invalid_parameter_value(
                "Invalid server_json.remotes entry. Expected each remote to be an object."
            )
        url = remote.get("url")
        if url is None:
            continue
        if not isinstance(url, str) or not url.strip():
            raise MlflowException.invalid_parameter_value(
                "Invalid server_json.remotes entry. Expected remote.url to be a non-empty string."
            )
        transport_str = "streamable-http" if remote.get("type") is None else remote.get("type")
        try:
            transport = MCPRemoteTransportType(transport_str)
        except ValueError as e:
            valid = ", ".join(repr(t.value) for t in MCPRemoteTransportType)
            raise MlflowException.invalid_parameter_value(
                f"Invalid transport_type {transport_str!r}. Valid values are: {valid}"
            ) from e

        candidate = url.strip()
        try:
            _validate_mcp_tool_discovery_url(candidate)
        except MlflowException as e:
            _logger.info(
                "Skipping MCP remote %r for tool discovery (%s); trying next remote if any",
                candidate,
                e,
            )
            continue
        return candidate, transport
    return None


def resolve_tools_for_create(
    server_json: dict[str, Any],
    tools: list[MCPTool] | None,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_MCP_TOOL_DISCOVER_TIMEOUT_SECONDS,
) -> list[MCPTool] | None:
    """Resolve ``tools`` for MCP server version create.

    * ``NOT_SET`` (Python default / JSON field omitted): best-effort auto-discover
      from the first discovery-eligible ``server_json.remotes[]`` URL when
      ``MLFLOW_ENABLE_MCP_TOOL_DISCOVERY`` is enabled. No eligible remote,
      discovery disabled, or discovery failure/timeout → ``None`` (create
      continues). Live scrape does not failover to later remotes.
    * ``None`` (explicit JSON null): store no tools; do not discover.
    * ``[]`` / a list: store as-is; do not discover.
    """
    if tools is not NOT_SET:
        return tools

    if not MLFLOW_ENABLE_MCP_TOOL_DISCOVERY.get():
        return None

    remote = _first_discovery_remote(server_json)
    if remote is None:
        return None

    url, transport = remote
    try:
        return discover_mcp_tools(
            url=url,
            transport_type=transport,
            headers=headers,
            timeout=timeout,
        )
    except Exception as e:
        _logger.warning(
            "MCP tool discovery failed for %r; creating version with tools=None: %s",
            url,
            e,
        )
        return None
