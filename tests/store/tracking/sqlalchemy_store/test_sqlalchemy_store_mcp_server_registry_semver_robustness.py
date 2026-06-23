from __future__ import annotations

from functools import cmp_to_key

import pytest

from mlflow.entities.mcp_server import MCPStatus
from mlflow.utils.semver_utils import compare_semver, parse_semver

from tests.utils.semver_test_support import generate_valid_semver_corpus

pytestmark = pytest.mark.notrackingurimock


def _server_json(name: str, version: str) -> dict[str, str]:
    return {"name": name, "version": version, "title": f"Test {name}"}


def _compare_versions_for_latest(left: str, right: str) -> int:
    if precedence := compare_semver(parse_semver(left), parse_semver(right)):
        return precedence
    return (left > right) - (left < right)


def _latest_version(versions: list[str]) -> str:
    return max(versions, key=cmp_to_key(_compare_versions_for_latest))


def _expected_latest_resolution(
    versions_and_statuses: list[tuple[str, MCPStatus]],
) -> tuple[str, MCPStatus]:
    active_versions = [
        version for version, status in versions_and_statuses if status == MCPStatus.ACTIVE
    ]
    fallback_versions = [
        version
        for version, status in versions_and_statuses
        if status in {MCPStatus.DRAFT, MCPStatus.DEPRECATED}
    ]
    chosen_pool = active_versions or fallback_versions
    expected_version = _latest_version(chosen_pool)
    expected_status = dict(versions_and_statuses)[expected_version]
    return expected_version, expected_status


def _assert_latest_resolution_surfaces(
    store, name: str, expected_version: str, expected_status: MCPStatus
) -> None:
    latest = store.get_latest_mcp_server_version(name)
    assert latest.version == expected_version
    assert latest.status == expected_status

    server = store.get_mcp_server(name)
    assert server.latest_version == expected_version
    assert server.status == expected_status

    latest_alias = store.get_mcp_server_version_by_alias(name, "latest")
    assert latest_alias.version == expected_version
    assert latest_alias.status == expected_status

    binding = store.create_mcp_access_binding(
        name,
        f"https://{name.rsplit('/', 1)[-1]}.example.com/latest",
        server_alias="latest",
    )
    assert binding.resolved_version is not None
    assert binding.resolved_version.version == expected_version
    assert binding.resolved_version.status == expected_status


@pytest.mark.parametrize("seed", [1, 7, 23, 41])
def test_latest_resolution_matches_seeded_active_semver_corpus(store, seed):
    name = f"io.github.test/seeded-active-{seed}"
    versions = generate_valid_semver_corpus(seed=seed, count=18)
    for version in versions:
        store.create_mcp_server_version(_server_json(name, version), status=MCPStatus.ACTIVE)

    expected_version = _latest_version(versions)
    _assert_latest_resolution_surfaces(store, name, expected_version, MCPStatus.ACTIVE)


@pytest.mark.parametrize("seed", [2, 11, 29])
def test_latest_resolution_fallback_matches_seeded_non_active_semver_corpus(store, seed):
    name = f"io.github.test/seeded-fallback-{seed}"
    versions = generate_valid_semver_corpus(seed=seed, count=16)
    versions_and_statuses = [
        (version, MCPStatus.DRAFT if index % 2 else MCPStatus.DEPRECATED)
        for index, version in enumerate(versions)
    ]
    for version, status in versions_and_statuses:
        store.create_mcp_server_version(_server_json(name, version), status=status)

    expected_version, expected_status = _expected_latest_resolution(versions_and_statuses)
    _assert_latest_resolution_surfaces(store, name, expected_version, expected_status)


def test_latest_resolution_prefers_active_pool_over_higher_non_active_versions(store):
    name = "io.github.test/prefers-active-pool"
    active_versions = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-beta.2",
        "1.0.0",
        "1.0.0+build.9",
    ]
    for version in active_versions:
        store.create_mcp_server_version(_server_json(name, version), status=MCPStatus.ACTIVE)

    for version in ("99.0.0", "100.0.0", "100.0.0+zzz"):
        store.create_mcp_server_version(_server_json(name, version), status=MCPStatus.DEPRECATED)

    expected_version = _latest_version(active_versions)
    _assert_latest_resolution_surfaces(store, name, expected_version, MCPStatus.ACTIVE)


def test_latest_resolution_uses_raw_version_string_as_final_tiebreaker(store):
    name = "io.github.test/build-tiebreak-seeded"
    versions_and_statuses = [
        ("7.2.1-beta+aaa", MCPStatus.ACTIVE),
        ("7.2.1-beta+mmm", MCPStatus.ACTIVE),
        ("7.2.1-beta+zzz", MCPStatus.ACTIVE),
    ]
    for version, status in versions_and_statuses:
        store.create_mcp_server_version(_server_json(name, version), status=status)

    expected_version, expected_status = _expected_latest_resolution(versions_and_statuses)
    assert expected_version == "7.2.1-beta+zzz"
    _assert_latest_resolution_surfaces(store, name, expected_version, expected_status)
