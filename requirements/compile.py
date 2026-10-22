"""Generate Konflux requirements lock files with multi-arch hash support.

For AIPCC requirements (konflux-aipcc, konflux-build-aipcc), runs uv pip compile
inside Docker containers for each target architecture, then merges the
per-architecture hashes into a single output file. Packages explicitly listed
in requirements/konflux-pypi.in are omitted from the final-image AIPCC output
so SBOM and CVE tooling see a single source of truth per shipped package.
Packages resolving to multiple versions get platform_machine markers;
single-version packages remain unmarked.

For PyPI requirements (konflux-pypi), runs a single uv pip compile since these
packages are built from source and don't need multi-arch hashes.

Usage:
    python requirements/compile.py [--image IMAGE]
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from packaging.markers import Marker
from pip._internal.network.session import PipSession
from pip._internal.req.req_install import InstallRequirement
from piptools._compat.pip_compat import parse_requirements
from piptools.utils import format_requirement, get_hashes_from_ireq

AIPCC_INDEX_URL = "https://console.redhat.com/api/pypi/public-rhai/rhoai/3.4/cpu-ubi9/simple"

DEFAULT_DOCKER_IMAGE = "registry.access.redhat.com/ubi9/python-312:9.7"

# Docker architecture names mapped to Python's platform.machine() values.
ARCHES = {
    "amd64": "x86_64",
    "arm64": "aarch64",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
}

# Packages that are expected to be unavailable on specific architectures
# (e.g. greenlet has no s390x wheel and is excluded via platform markers).
ARCH_MISSING_ALLOWLIST: dict[str, set[str]] = {
    "ppc64le": {"hf-xet"},
    "s390x": {"greenlet", "hf-xet"},
}

REPO_ROOT = Path(__file__).resolve().parent.parent
KONFLUX_PYPI_IN = REPO_ROOT / "requirements/konflux-pypi.in"


@dataclass
class CompileTarget:
    name: str
    in_files: list[str]
    out_file: str
    index_url: str | None = None
    emit_index_url: bool = False
    extra_uv_args: list[str] = field(default_factory=list)


@dataclass
class LockedRequirement:
    ireq: InstallRequirement
    hashes: set[str] = field(default_factory=set)
    arches: set[str] = field(default_factory=set)


MULTIARCH_TARGETS = [
    CompileTarget(
        name="konflux-aipcc",
        in_files=["pyproject.toml", "requirements/konflux-aipcc.in"],
        out_file="requirements/konflux-aipcc-requirements.txt",
        index_url=AIPCC_INDEX_URL,
        emit_index_url=True,
        extra_uv_args=[
            "--no-emit-package",
            "mlflow",
            "--extra",
            "kubernetes",
            "--prerelease=allow",
        ],
    ),
    CompileTarget(
        name="konflux-build-aipcc",
        in_files=["requirements/konflux-build-aipcc.in"],
        out_file="requirements/konflux-build-aipcc-requirements.txt",
        index_url=AIPCC_INDEX_URL,
        emit_index_url=True,
        extra_uv_args=["--prerelease=allow"],
    ),
]

PYPI_TARGET = CompileTarget(
    name="konflux-pypi",
    in_files=["requirements/konflux-pypi.in"],
    out_file="requirements/konflux-pypi-requirements.txt",
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _canonicalize(name: str) -> str:
    """PEP 503 normalization so we can match the same package across arch outputs."""
    return re.sub(r"[-_.]+", "-", name).lower()


@cache
def read_requirements_names(path: Path) -> frozenset[str]:
    session = PipSession()
    return frozenset(
        _canonicalize(ireq.req.name) for ireq in parse_requirements(str(path), session=session)
    )


def run_uv_compile_in_docker(
    target: CompileTarget,
    arch: str,
    image: str,
) -> str:
    """Run uv pip compile inside a Docker container for the given architecture.

    Returns the raw uv output as a string.
    """
    uv_cmd = [
        "uv",
        "pip",
        "compile",
        "--generate-hashes",
        "--no-header",
        "--python-version",
        "3.12",
        "--output-file",
        "-",
    ]
    if target.index_url:
        uv_cmd += ["--index-url", target.index_url]
    if target.emit_index_url:
        uv_cmd.append("--emit-index-url")
    uv_cmd += target.extra_uv_args
    uv_cmd += [f"/src/{f}" for f in target.in_files]

    shell_cmd = "pip install -q uv && " + shlex.join(uv_cmd)

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        f"linux/{arch}",
        "-v",
        f"{REPO_ROOT}:/src:ro,z",
        image,
        "sh",
        "-c",
        shell_cmd,
    ]

    log(f"  [{arch}] running uv pip compile for {target.name} ...")
    result = subprocess.run(
        docker_cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(result.stderr)
        raise SystemExit(
            f"uv pip compile failed for {target.name} on {arch} (exit {result.returncode})."
        )

    return result.stdout


def parse_and_collect_hashes(
    arch_outputs: dict[str, str],
) -> dict[tuple[str, str], LockedRequirement]:
    """Merge hashes by (canonical name, version), allowing one package entry per arch."""
    session = PipSession()
    requirements: dict[tuple[str, str], LockedRequirement] = {}
    package_arches: dict[str, set[str]] = {}

    for arch, raw_output in arch_outputs.items():
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write(raw_output)
            tmp_path = tmp.name

        try:
            ireqs = list(parse_requirements(tmp_path, session=session))
        finally:
            os.unlink(tmp_path)

        for ireq in ireqs:
            name = _canonicalize(ireq.req.name)
            version = str(ireq.req.specifier)
            arches = package_arches.setdefault(name, set())
            if arch in arches:
                raise SystemExit(f"Duplicate package {name} for architecture {arch}.")
            arches.add(arch)

            requirement = requirements.setdefault((name, version), LockedRequirement(ireq))
            requirement.arches.add(arch)
            requirement.hashes |= get_hashes_from_ireq(ireq)

    all_arches = set(arch_outputs)
    for name, arches in package_arches.items():
        if missing := all_arches - arches:
            allowed = {a for a in missing if name in ARCH_MISSING_ALLOWLIST.get(a, set())}

            if unexpected := missing - allowed:
                raise SystemExit(
                    f"Package {name} is missing for architecture(s): "
                    f"{', '.join(sorted(unexpected))}. "
                    "All architectures must resolve the same set of packages. "
                    "If this is expected, add the package to ARCH_MISSING_ALLOWLIST."
                )

    return requirements


def write_multiarch_output(
    target: CompileTarget,
    requirements: dict[tuple[str, str], LockedRequirement],
    excluded_names: set[str] | None = None,
) -> None:
    out_path = REPO_ROOT / target.out_file
    parts: list[str] = []

    arches_str = ", ".join(ARCHES)
    parts.append(
        "#\n"
        "# This file is autogenerated by uv via requirements/compile.py\n"
        f"# for the following architectures: {arches_str}\n"
        "#\n"
        "#    python requirements/compile.py\n"
        "#\n"
    )

    if target.emit_index_url and target.index_url:
        parts.append(f"--index-url {target.index_url}\n\n")

    version_counts = Counter(name for name, _ in requirements)
    for (name, _), requirement in sorted(requirements.items()):
        if excluded_names and name in excluded_names:
            continue
        marker = None
        if version_counts[name] > 1:
            marker = Marker(
                " or ".join(
                    f'platform_machine == "{ARCHES[arch]}"' for arch in sorted(requirement.arches)
                )
            )
        parts.append(
            format_requirement(requirement.ireq, marker=marker, hashes=requirement.hashes) + "\n"
        )

    out_path.write_text("".join(parts))
    log(f"  wrote {target.out_file}")


def pull_arch_images(image: str) -> dict[str, str]:
    """Pre-pull the Docker image for each architecture and tag uniquely.

    Docker's local image cache can conflict when pulling the same multi-arch
    tag for different platforms concurrently, so we pull sequentially and
    assign a unique tag per architecture.

    Returns a mapping of arch -> tagged image name.
    """
    tagged: dict[str, str] = {}
    for arch in ARCHES:
        arch_tag = f"{image}-{arch}"
        log(f"  pulling {image} for {arch} ...")
        result = subprocess.run(
            ["docker", "pull", "--platform", f"linux/{arch}", image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(result.stderr)
            raise SystemExit(f"docker pull failed for {image} on {arch}.")
        subprocess.run(
            ["docker", "tag", image, arch_tag],
            capture_output=True,
            text=True,
            check=True,
        )
        tagged[arch] = arch_tag
    return tagged


def compile_multiarch(target: CompileTarget, image: str) -> None:
    log(f"Compiling {target.name} (multi-arch) ...")

    arch_images = pull_arch_images(image)

    try:
        arch_outputs: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(ARCHES)) as pool:
            futures = {
                pool.submit(run_uv_compile_in_docker, target, arch, arch_images[arch]): arch
                for arch in ARCHES
            }
            for future in as_completed(futures):
                arch = futures[future]
                arch_outputs[arch] = future.result()

        requirements = parse_and_collect_hashes(arch_outputs)

        excluded_names = (
            read_requirements_names(KONFLUX_PYPI_IN) if target.name == "konflux-aipcc" else None
        )
        write_multiarch_output(
            target,
            requirements,
            excluded_names=excluded_names,
        )
    finally:
        for arch_tag in arch_images.values():
            subprocess.run(["docker", "rmi", arch_tag], capture_output=True)


def compile_pypi(target: CompileTarget) -> None:
    log(f"Compiling {target.name} (single-arch, uv) ...")

    out_path = REPO_ROOT / target.out_file
    uv_cmd = [
        "uv",
        "pip",
        "compile",
        *target.in_files,
        "--python-platform",
        "linux",
        "--python-version",
        "3.12",
        "--no-deps",
        "--generate-hashes",
        "-o",
        str(out_path),
    ]

    result = subprocess.run(
        uv_cmd,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        log(result.stderr)
        raise SystemExit(f"uv pip compile failed for {target.name}.")

    content = out_path.read_text()
    content = re.sub(
        r"^# This file was autogenerated by uv via the following command:\n"
        r"#    .+\n",
        "# This file was autogenerated by uv via requirements/compile.py\n"
        "#\n"
        "#    python requirements/compile.py\n",
        content,
    )
    out_path.write_text(content)

    log(f"  wrote {target.out_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Konflux requirements lock files with multi-arch hash support.",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_DOCKER_IMAGE,
        help=f"Docker image for uv pip compile (default: {DEFAULT_DOCKER_IMAGE})",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)

    for target in MULTIARCH_TARGETS:
        compile_multiarch(target, args.image)

    compile_pypi(PYPI_TARGET)

    log("Done.")


if __name__ == "__main__":
    main()
