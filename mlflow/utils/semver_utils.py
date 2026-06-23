from __future__ import annotations

import re
from dataclasses import dataclass

from mlflow.exceptions import MlflowException

_MAX_SEMVER_LENGTH = 128
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"\.(?P<minor>0|[1-9]\d*)"
    r"\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<buildmetadata>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: str | None = None


def parse_semver(version: str, *, param_name: str = "version") -> SemVer:
    if len(version) > _MAX_SEMVER_LENGTH:
        raise MlflowException.invalid_parameter_value(
            f"Invalid semantic version for {param_name}: '{version}' "
            f"(maximum length is {_MAX_SEMVER_LENGTH} characters)"
        )
    match = _SEMVER_RE.fullmatch(version)
    if not match:
        raise MlflowException.invalid_parameter_value(
            f"Invalid semantic version for {param_name}: '{version}'"
        )
    return SemVer(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=(
            tuple(match.group("prerelease").split(".")) if match.group("prerelease") else ()
        ),
        build=match.group("buildmetadata"),
    )


def compare_semver(left: SemVer, right: SemVer) -> int:
    for left_part, right_part in (
        (left.major, right.major),
        (left.minor, right.minor),
        (left.patch, right.patch),
    ):
        if left_part != right_part:
            return -1 if left_part < right_part else 1

    if not left.prerelease and not right.prerelease:
        return 0
    if not left.prerelease:
        return 1
    if not right.prerelease:
        return -1

    for left_identifier, right_identifier in zip(left.prerelease, right.prerelease):
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            left_value = int(left_identifier)
            right_value = int(right_identifier)
            if left_value != right_value:
                return -1 if left_value < right_value else 1
            continue
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        if left_identifier != right_identifier:
            return -1 if left_identifier < right_identifier else 1

    if len(left.prerelease) != len(right.prerelease):
        return -1 if len(left.prerelease) < len(right.prerelease) else 1

    return 0


def semver_sort_key(version: str) -> tuple[int, int, int, tuple[tuple[int, int | str], ...]]:
    parsed = parse_semver(version)
    prerelease_key = tuple(
        (0, int(identifier)) if identifier.isdigit() else (1, identifier)
        for identifier in parsed.prerelease
    )
    return parsed.major, parsed.minor, parsed.patch, prerelease_key
