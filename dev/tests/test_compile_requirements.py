import pytest

compiler = pytest.importorskip(
    "requirements.compile",
    reason="The Konflux lock compiler requires pip-tools",
    exc_type=ModuleNotFoundError,
)


@pytest.fixture
def write_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    target = compiler.CompileTarget("test", [], "requirements.txt")

    def write(arch_outputs, excluded_names=None):
        requirements = compiler.parse_and_collect_hashes(arch_outputs)
        compiler.write_multiarch_output(target, requirements, excluded_names=excluded_names)
        path = tmp_path / target.out_file
        parsed = list(compiler.parse_requirements(str(path), session=compiler.PipSession()))
        return path.read_text(), parsed

    return write


def test_shared_version_merges_hashes_without_marker(write_lock):
    outputs = {arch: f"example==1.0 --hash=sha256:{arch}\n" for arch in compiler.ARCHES}
    _, requirements = write_lock(outputs)

    assert len(requirements) == 1
    assert requirements[0].markers is None
    assert compiler.get_hashes_from_ireq(requirements[0]) == {
        f"sha256:{arch}" for arch in compiler.ARCHES
    }


@pytest.mark.parametrize("name", ["protobuf", "another-package"])
def test_version_variants_select_one_version_per_machine(write_lock, name):
    outputs = {
        arch: f"{name}=={'7.35.1' if arch == 's390x' else '7.34.1'} --hash=sha256:{arch}\n"
        for arch in compiler.ARCHES
    }
    text, requirements = write_lock(outputs)

    assert len(requirements) == 2
    for arch, machine in compiler.ARCHES.items():
        selected = [r for r in requirements if r.markers.evaluate({"platform_machine": machine})]
        assert len(selected) == 1
        assert str(selected[0].req.specifier) == ("==7.35.1" if arch == "s390x" else "==7.34.1")
        expected_arches = {"s390x"} if arch == "s390x" else set(compiler.ARCHES) - {"s390x"}
        assert compiler.get_hashes_from_ireq(selected[0]) == {
            f"sha256:{a}" for a in expected_arches
        }

    reversed_text, _ = write_lock(dict(reversed(list(outputs.items()))))
    assert text == reversed_text


@pytest.mark.parametrize("version", ["1.0", "2.0"])
def test_duplicate_package_for_arch_is_rejected(version):
    with pytest.raises(SystemExit, match="Duplicate package some-package for architecture amd64"):
        compiler.parse_and_collect_hashes(
            {"amd64": f"Some_Package==1.0\nsome-package=={version}\n"}
        )


def test_unexpected_missing_package_is_rejected():
    outputs = dict.fromkeys(compiler.ARCHES, "example==1.0\n")
    outputs["s390x"] = ""
    with pytest.raises(
        SystemExit, match="Package example is missing for architecture\\(s\\): s390x"
    ):
        compiler.parse_and_collect_hashes(outputs)


@pytest.mark.parametrize(
    ("name", "missing_arches"),
    [("greenlet", {"s390x"}), ("hf-xet", {"ppc64le", "s390x"})],
)
def test_single_version_stays_unmarked_when_missing_on_arch(write_lock, name, missing_arches):
    outputs = {
        arch: f"{name}==1.0\n" if arch not in missing_arches else "" for arch in compiler.ARCHES
    }
    _, requirements = write_lock(outputs)

    assert len(requirements) == 1
    assert requirements[0].markers is None


def test_excluded_package_omits_all_versions(write_lock):
    outputs = {
        arch: f"example=={'2.0' if arch == 's390x' else '1.0'}\n" for arch in compiler.ARCHES
    }
    _, requirements = write_lock(outputs, excluded_names={"example"})
    assert requirements == []
