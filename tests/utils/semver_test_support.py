from __future__ import annotations

import random
import re
import string

from mlflow.utils.semver_utils import SemVer

SPEC_PRECEDENCE_CHAIN = (
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-alpha.beta",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.11",
    "1.0.0-rc.1",
    "1.0.0",
)

PUBLIC_VALID_EXAMPLES = (
    "1.2.3--",
    "1.2.3--.-.-",
    "1.2.3-----",
    "1.2.3-4.3.2.1",
    "1.2.3--1.-.abc+000001.-2.3e7",
    "1.0.0-0",
    "1.0.0-1",
    "1.0.0--1",
    "1.0.0-z",
    "1.0.0-zz",
    "1.0.0-rc3",
    "1.0.0-rc12",
    "1.0.0-x-y-z.--",
    "0.0.0-0",
    "0.0.0+build-0",
    "42.0.7-alpha-1.beta-2+build-3",
)

PUBLIC_INVALID_EXAMPLES = (
    "1️⃣.2.3",
    "⒈2.3",
    "⒈.2.3",
    "①.2.3",
    "𝟷.2.3",
    "².2.3",
    "₂.2.3",
    "1.0.0-01",
    "1.0.0-00",
    "1.0.0-rc.01",
    "1.0.0-alpha_beta",
    "1.0.0-alpha..beta",
    "1.0.0-alpha.",
    "1.0.0-",
    "1.0.0+meta+meta",
    "1.0.0+meta_meta",
    "v1.0.0",
    "1.0",
    "1.0.0.0",
)

PUBLIC_PRECEDENCE_PAIRS = (
    ("0.9.99", "1.0.0"),
    ("0.9.0", "0.10.0"),
    ("1.0.0-0.0", "1.0.0-0.0.0"),
    ("1.0.0-9999", "1.0.0--"),
    ("1.0.0-99", "1.0.0-100"),
    ("1.0.0-alpha", "1.0.0-alpha.1"),
    ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
    ("1.0.0-alpha.beta", "1.0.0-beta"),
    ("1.0.0-beta", "1.0.0-beta.2"),
    ("1.0.0-beta.2", "1.0.0-beta.11"),
    ("1.0.0-beta.11", "1.0.0-rc.1"),
    ("1.0.0-rc.1", "1.0.0"),
    ("1.0.0-0", "1.0.0--1"),
    ("1.0.0-0", "1.0.0-1"),
    ("1.0.0-1.0", "1.0.0-1.-1"),
    ("1.0.0-alpha", "1.0.0-alpha1"),
    ("1.0.0-alpha", "1.0.0-alpha-1"),
    ("1.0.0-rc12", "1.0.0-rc3"),
    ("1.0.0-z", "1.0.0-zz"),
)

_TEXT_IDENTIFIER_ALPHABET = string.ascii_letters + string.digits + "-"
_BUILD_IDENTIFIER_ALPHABET = string.ascii_letters + string.digits + "-"


def render_semver(
    major: int,
    minor: int,
    patch: int,
    prerelease: tuple[str, ...] = (),
    build: tuple[str, ...] = (),
) -> str:
    version = f"{major}.{minor}.{patch}"
    if prerelease:
        version += "-" + ".".join(prerelease)
    if build:
        version += "+" + ".".join(build)
    return version


def reference_compare_identifiers(left: str, right: str) -> int:
    left_is_numeric = left.isdigit()
    right_is_numeric = right.isdigit()

    if left_is_numeric and right_is_numeric:
        left_num = int(left)
        right_num = int(right)
        return (left_num > right_num) - (left_num < right_num)

    if left_is_numeric != right_is_numeric:
        return -1 if left_is_numeric else 1

    return (left > right) - (left < right)


def reference_compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left:
        return 0 if not right else 1
    if not right:
        return -1

    for left_identifier, right_identifier in zip(left, right):
        if comparison := reference_compare_identifiers(left_identifier, right_identifier):
            return comparison

    if len(left) != len(right):
        return -1 if len(left) < len(right) else 1

    return 0


def reference_compare_semver(left: SemVer, right: SemVer) -> int:
    left_core = (left.major, left.minor, left.patch)
    right_core = (right.major, right.minor, right.patch)
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)
    return reference_compare_prerelease(left.prerelease, right.prerelease)


def generate_valid_semver_corpus(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    versions = set(SPEC_PRECEDENCE_CHAIN)
    versions.update(PUBLIC_VALID_EXAMPLES)

    while len(versions) < count:
        major = _random_core_component(rng)
        minor = _random_core_component(rng)
        patch = _random_core_component(rng)
        prerelease = _random_prerelease(rng)
        build = _random_build(rng)
        version = render_semver(major, minor, patch, prerelease=prerelease, build=build)
        if len(version) <= 128:
            versions.add(version)

    return sorted(versions)


def generate_invalid_semver_mutations(valid_versions: list[str], seed: int) -> list[str]:
    rng = random.Random(seed)
    invalids = set(PUBLIC_INVALID_EXAMPLES)

    for version in rng.sample(valid_versions, min(32, len(valid_versions))):
        core, prerelease, build = _split_semver(version)
        major, minor, patch = core.split(".")

        invalids.add(f"v{version}")
        invalids.add(f"{major}.{minor}")
        invalids.add(f"{major}.{minor}.{patch}.0")
        invalids.add(f"{_with_leading_zero(major)}.{minor}.{patch}")
        invalids.add(f"{major}.{_with_leading_zero(minor)}.{patch}")
        invalids.add(f"{major}.{minor}.{_with_leading_zero(patch)}")
        if build is None:
            invalids.add(f"{version}+meta+again")
        else:
            invalids.add(
                f"{core}{f'-{prerelease}' if prerelease is not None else ''}+{build}+again"
            )

        if prerelease is None:
            invalids.add(f"{core}-01" + (f"+{build}" if build is not None else ""))
            invalids.add(f"{core}-." + (f"+{build}" if build is not None else ""))
            invalids.add(f"{core}-alpha..1" + (f"+{build}" if build is not None else ""))
            invalids.add(f"{core}-alpha_beta" + (f"+{build}" if build is not None else ""))
        else:
            suffix = f"+{build}" if build is not None else ""
            invalids.add(f"{core}-{prerelease}.{suffix}")
            invalids.add(f"{core}-{prerelease}..1{suffix}")
            invalids.add(f"{core}-{_with_invalid_prerelease_character(prerelease)}{suffix}")
            invalids.add(f"{core}-{_inject_leading_zero_numeric_identifier(prerelease)}{suffix}")

        if build is None:
            invalids.add(f"{version}+meta_meta")
        else:
            invalids.add(f"{core}{f'-{prerelease}' if prerelease is not None else ''}+{build}.")
            invalids.add(f"{core}{f'-{prerelease}' if prerelease is not None else ''}+{build}_")

    return sorted(invalids)


def _random_core_component(rng: random.Random) -> int:
    return rng.choice([
        0,
        1,
        2,
        9,
        10,
        99,
        100,
        rng.randint(3, 500),
        rng.randint(1000, 100000),
    ])


def _random_prerelease(rng: random.Random) -> tuple[str, ...]:
    if rng.random() < 0.4:
        return ()

    length = rng.randint(1, 4)
    return tuple(_random_prerelease_identifier(rng) for _ in range(length))


def _random_build(rng: random.Random) -> tuple[str, ...]:
    if rng.random() < 0.6:
        return ()

    length = rng.randint(1, 3)
    return tuple(_random_build_identifier(rng) for _ in range(length))


def _random_prerelease_identifier(rng: random.Random) -> str:
    if rng.random() < 0.35:
        return _random_numeric_identifier(rng)

    return _random_text_identifier(rng)


def _random_numeric_identifier(rng: random.Random) -> str:
    if rng.random() < 0.25:
        return "0"
    first = rng.choice("123456789")
    rest = "".join(rng.choice(string.digits) for _ in range(rng.randint(0, 4)))
    return first + rest


def _random_text_identifier(rng: random.Random) -> str:
    length = rng.randint(1, 10)
    while True:
        candidate = "".join(rng.choice(_TEXT_IDENTIFIER_ALPHABET) for _ in range(length))
        if not candidate.isdigit():
            return candidate


def _random_build_identifier(rng: random.Random) -> str:
    length = rng.randint(1, 12)
    return "".join(rng.choice(_BUILD_IDENTIFIER_ALPHABET) for _ in range(length))


def _split_semver(version: str) -> tuple[str, str | None, str | None]:
    core_and_prerelease, has_build, build = version.partition("+")
    core, has_prerelease, prerelease = core_and_prerelease.partition("-")
    return core, prerelease if has_prerelease else None, build if has_build else None


def _with_leading_zero(component: str) -> str:
    return "00" if component == "0" else f"0{component}"


def _inject_leading_zero_numeric_identifier(prerelease: str) -> str:
    pattern = re.compile(r"(^|\.)([1-9]\d*)(?=\.|$)")
    match = pattern.search(prerelease)
    if match is None:
        return "01"

    start, end = match.span(2)
    return prerelease[:start] + "0" + prerelease[start:end] + prerelease[end:]


def _with_invalid_prerelease_character(prerelease: str) -> str:
    if "-" in prerelease:
        return prerelease.replace("-", "_", 1)
    return f"{prerelease}_"
