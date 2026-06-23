from __future__ import annotations

from functools import cmp_to_key
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from mlflow.server.registry_fastapi_app import create_registry_fastapi_app
from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore
from mlflow.utils.semver_utils import compare_semver, parse_semver

from tests.utils.semver_test_support import generate_valid_semver_corpus

PREFIX = "/ajax-api/3.0/mlflow/mcp-servers"


def _server_json(name: str, version: str, **extra: Any) -> dict[str, Any]:
    payload = {"name": name, "version": version}
    payload.update(extra)
    return payload


def _encode_path_param(value: str) -> str:
    return quote(value, safe="")


@pytest.fixture
def store(tmp_path: Path):
    artifact_uri = tmp_path / "artifacts"
    artifact_uri.mkdir()
    return SqlAlchemyStore(f"sqlite:///{tmp_path / 'test.db'}", artifact_uri.as_uri())


@pytest.fixture
def client(store):
    with mock.patch(
        "mlflow.server.handlers._get_tracking_store",
        return_value=store,
    ):
        yield TestClient(create_registry_fastapi_app())


def _compare_versions_for_latest(left: str, right: str) -> int:
    if precedence := compare_semver(parse_semver(left), parse_semver(right)):
        return precedence
    return (left > right) - (left < right)


def _latest_version(versions: list[str]) -> str:
    return max(versions, key=cmp_to_key(_compare_versions_for_latest))


def _expected_latest_resolution(
    versions_and_statuses: list[tuple[str, str]],
) -> tuple[str, str]:
    active_versions = [version for version, status in versions_and_statuses if status == "active"]
    fallback_versions = [
        version for version, status in versions_and_statuses if status in {"draft", "deprecated"}
    ]
    chosen_pool = active_versions or fallback_versions
    expected_version = _latest_version(chosen_pool)
    expected_status = dict(versions_and_statuses)[expected_version]
    return expected_version, expected_status


def _post_version(client: TestClient, name: str, version: str, status: str) -> None:
    response = client.post(
        f"{PREFIX}/{_encode_path_param(name)}/versions",
        json={"server_json": _server_json(name, version), "status": status},
    )
    assert response.status_code == 200


def _assert_latest_resolution_surfaces(
    client: TestClient, name: str, expected_version: str, expected_status: str
) -> None:
    alias_response = client.get(f"{PREFIX}/{_encode_path_param(name)}/aliases/latest")
    assert alias_response.status_code == 200
    assert alias_response.json()["version"] == expected_version
    assert alias_response.json()["status"] == expected_status

    server_response = client.get(f"{PREFIX}/{_encode_path_param(name)}")
    assert server_response.status_code == 200
    assert server_response.json()["latest_version"] == expected_version
    assert server_response.json()["status"] == expected_status

    binding_response = client.post(
        f"{PREFIX}/{_encode_path_param(name)}/bindings",
        json={
            "endpoint_url": f"https://{name.rsplit('/', 1)[-1]}.example.com/latest",
            "server_alias": "latest",
        },
    )
    assert binding_response.status_code == 200
    assert binding_response.json()["resolved_version"]["version"] == expected_version
    assert binding_response.json()["resolved_version"]["status"] == expected_status


@pytest.mark.parametrize("seed", [1, 7, 23])
def test_latest_alias_matches_seeded_active_semver_corpus(client, seed):
    name = f"com.example/seeded-active-{seed}"
    versions = generate_valid_semver_corpus(seed=seed, count=12)
    for version in versions:
        _post_version(client, name, version, "active")

    expected_version = _latest_version(versions)
    _assert_latest_resolution_surfaces(client, name, expected_version, "active")


@pytest.mark.parametrize("seed", [2, 11])
def test_latest_alias_fallback_matches_seeded_non_active_semver_corpus(client, seed):
    name = f"com.example/seeded-fallback-{seed}"
    versions = generate_valid_semver_corpus(seed=seed, count=10)
    versions_and_statuses = [
        (version, "draft" if index % 2 else "deprecated") for index, version in enumerate(versions)
    ]
    for version, status in versions_and_statuses:
        _post_version(client, name, version, status)

    expected_version, expected_status = _expected_latest_resolution(versions_and_statuses)
    _assert_latest_resolution_surfaces(client, name, expected_version, expected_status)


def test_latest_alias_prefers_active_pool_over_higher_non_active_versions(client):
    name = "com.example/prefers-active-pool"
    active_versions = ["1.0.0-alpha", "1.0.0-beta.2", "1.0.0", "1.0.0+build.9"]
    for version in active_versions:
        _post_version(client, name, version, "active")

    for version in ("99.0.0", "100.0.0", "100.0.0+zzz"):
        _post_version(client, name, version, "deprecated")

    expected_version = _latest_version(active_versions)
    _assert_latest_resolution_surfaces(client, name, expected_version, "active")


def test_latest_alias_uses_raw_version_string_as_final_tiebreaker(client):
    name = "com.example/build-tiebreak-seeded"
    versions_and_statuses = [
        ("7.2.1-beta+aaa", "active"),
        ("7.2.1-beta+mmm", "active"),
        ("7.2.1-beta+zzz", "active"),
    ]
    for version, status in versions_and_statuses:
        _post_version(client, name, version, status)

    expected_version, expected_status = _expected_latest_resolution(versions_and_statuses)
    assert expected_version == "7.2.1-beta+zzz"
    _assert_latest_resolution_surfaces(client, name, expected_version, expected_status)
