from itertools import product

import pytest

from mlflow.exceptions import MlflowException
from mlflow.utils.semver_utils import SemVer, compare_semver, parse_semver


def _compare_identifiers(left: str, right: str) -> int:
    left_is_numeric = left.isdigit()
    right_is_numeric = right.isdigit()

    if left_is_numeric and right_is_numeric:
        left_num = int(left)
        right_num = int(right)
        return (left_num > right_num) - (left_num < right_num)

    if left_is_numeric != right_is_numeric:
        return -1 if left_is_numeric else 1

    return (left > right) - (left < right)


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left:
        return 0 if not right else 1
    if not right:
        return -1

    for left_id, right_id in zip(left, right):
        if comparison := _compare_identifiers(left_id, right_id):
            return comparison

    if len(left) != len(right):
        return -1 if len(left) < len(right) else 1

    return 0


def _compare_semver_precedence(left: SemVer, right: SemVer) -> int:
    left_core = (left.major, left.minor, left.patch)
    right_core = (right.major, right.minor, right.patch)
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)
    return _compare_prerelease(left.prerelease, right.prerelease)


def test_parse_semver_returns_structured_components():
    assert parse_semver("1.2.3") == SemVer(major=1, minor=2, patch=3)


def test_parse_semver_preserves_prerelease_and_build_metadata():
    assert parse_semver("1.0.0-beta.2+exp.sha.5114f85") == SemVer(
        major=1,
        minor=0,
        patch=0,
        prerelease=("beta", "2"),
        build="exp.sha.5114f85",
    )


@pytest.mark.parametrize(
    "valid",
    [
        "0.0.4",
        "1.2.3",
        "10.20.30",
        "1.1.2-prerelease+meta",
        "1.1.2+meta",
        "1.1.2+meta-valid",
        "1.0.0-alpha",
        "1.0.0-beta",
        "1.0.0-alpha.beta",
        "1.0.0-alpha.beta.1",
        "1.0.0-alpha.1",
        "1.0.0-alpha0.valid",
        "1.0.0-alpha.0valid",
        "1.0.0-alpha-a.b-c-somethinglong+build.1-aef.1-its-okay",
        "1.0.0-rc.1+build.1",
        "2.0.0-rc.1+build.123",
        "1.2.3-beta",
        "10.2.3-DEV-SNAPSHOT",
        "1.2.3-SNAPSHOT-123",
        "1.0.0",
        "2.0.0",
        "1.1.7",
        "2.0.0+build.1848",
        "2.0.1-alpha.1227",
        "1.0.0-alpha+beta",
        "1.0.0-0.3.7",
        "1.0.0-x.7.z.92",
        "1.2.3--",
        "1.2.3--.-.-",
        "1.2.3-----",
        "1.2.3-4.3.2.1",
        "1.2.3--1.-.abc+000001.-2.3e7",
        "1.2.3----RC-SNAPSHOT.12.9.1--.12+788",
        "1.2.3----R-S.12.9.1--.12+meta",
        "1.2.3----RC-SNAPSHOT.12.9.1--.12",
        "1.0.0+0.build.1-rc.10000aaa-kk-0.1",
        "99999999999999999999999.999999999999999999.99999999999999999",
        "1.0.0--1",
        "1.0.0-1.-1",
        "1.0.0-0A.is.legal",
    ],
)
def test_parse_semver_accepts_valid_edge_cases(valid):
    parse_semver(valid)


@pytest.mark.parametrize(
    "invalid",
    [
        "1.0",
        "latest",
        "v1.0.0",
        "01.0.0",
        "1.0.0.0",
        "",
        "1.2.3-00",
        "1.2.3-01",
        "1.2.3-.1",
        "1.2.3-a.",
        "1.2.3-...",
        "1.1.2+.123",
        "alpha",
        "alpha.beta",
        "alpha.beta.1",
        "1.0.0-alpha_beta",
        "1.0.0-alpha..1",
        "1.0.0-0123",
        "1.0.0-0123.0123",
        "+invalid",
        "-invalid",
        "-invalid+invalid",
        "-invalid.01",
        "alpha.1",
        "alpha+beta",
        "alpha_beta",
        "alpha.",
        "alpha..",
        "beta",
        "-alpha.",
        "1.0.0-alpha...1",
        "1.0.0-alpha....1",
        "1.0.0-alpha.....1",
        "1.0.0-alpha......1",
        "1.0.0-alpha.......1",
        "1.01.1",
        "1.1.01",
        "1.2.3.DEV",
        "1.2-SNAPSHOT",
        "1.2.31.2.3----RC-SNAPSHOT.12.09.1--..12+788",
        "1.2-RC-SNAPSHOT",
        "-1.0.3-gamma+b7718",
        "+justmeta",
        "9.8.7+meta+meta",
        "9.8.7-whatever+meta+meta",
        "99999999999999999999999.999999999999999999.99999999999999999----RC-SNAPSHOT.12.09.1--------------------------------..12",
    ],
)
def test_parse_semver_rejects_invalid_versions(invalid):
    with pytest.raises(MlflowException, match="Invalid semantic version"):
        parse_semver(invalid)


def test_parse_semver_rejects_versions_longer_than_storage_limit():
    too_long = "1.0.0-" + ("a" * 123)
    with pytest.raises(MlflowException, match="maximum length is 128 characters"):
        parse_semver(too_long)


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.0.0-alpha", "1.0.0-alpha1"),
        ("1.0.0-alpha", "1.0.0-alpha-1"),
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
        ("1.0.0-alpha.beta", "1.0.0-beta"),
        ("1.0.0-beta", "1.0.0-beta.2"),
        ("1.0.0-beta.2", "1.0.0-beta.11"),
        ("1.0.0-beta.11", "1.0.0-rc.1"),
        ("1.0.0-rc.1", "1.0.0"),
        ("1.0.0-0.0", "1.0.0-0.0.0"),
        ("1.0.0-99", "1.0.0-100"),
        ("1.0.0-0", "1.0.0--1"),
        ("1.0.0-0", "1.0.0-1"),
        ("1.0.0-1.0", "1.0.0-1.-1"),
        ("0.9.0", "0.10.0"),
        ("0.9.99", "1.0.0"),
    ],
)
def test_compare_semver_matches_spec_examples(lower, higher):
    lower_parsed = parse_semver(lower)
    higher_parsed = parse_semver(higher)

    assert _compare_semver_precedence(lower_parsed, higher_parsed) == -1
    assert compare_semver(lower_parsed, higher_parsed) == -1


def test_compare_semver_ignores_build_metadata_for_precedence():
    left = parse_semver("1.0.0-alpha+001")
    right = parse_semver("1.0.0-alpha+exp.sha.5114f85")

    assert _compare_semver_precedence(left, right) == 0
    assert compare_semver(left, right) == 0


def test_compare_semver_matches_reference_comparator_for_generated_corpus():
    identifier_pool = [
        "0",
        "1",
        "2",
        "10",
        "alpha",
        "alpha1",
        "alpha-1",
        "beta",
        "rc",
        "--1",
    ]
    versions = [parse_semver("1.0.0")]
    versions.extend(parse_semver(f"1.0.0-{identifier}") for identifier in identifier_pool)
    for length in (2, 3):
        versions.extend(
            parse_semver("1.0.0-" + ".".join(parts))
            for parts in product(identifier_pool, repeat=length)
        )

    for left in versions:
        for right in versions:
            assert compare_semver(left, right) == _compare_semver_precedence(left, right)
