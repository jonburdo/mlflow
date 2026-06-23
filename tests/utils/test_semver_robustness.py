from __future__ import annotations

from functools import cmp_to_key

import pytest

from mlflow.exceptions import MlflowException
from mlflow.utils.semver_utils import compare_semver, parse_semver

from tests.utils.semver_test_support import (
    PUBLIC_INVALID_EXAMPLES,
    PUBLIC_PRECEDENCE_PAIRS,
    PUBLIC_VALID_EXAMPLES,
    SPEC_PRECEDENCE_CHAIN,
    generate_invalid_semver_mutations,
    generate_valid_semver_corpus,
    reference_compare_semver,
)


@pytest.mark.parametrize("version", PUBLIC_VALID_EXAMPLES)
def test_parse_semver_accepts_public_edge_examples(version):
    parse_semver(version)


@pytest.mark.parametrize("version", PUBLIC_INVALID_EXAMPLES)
def test_parse_semver_rejects_public_invalid_examples(version):
    with pytest.raises(MlflowException, match="Invalid semantic version"):
        parse_semver(version)


@pytest.mark.parametrize("seed", [1, 7, 21, 99])
def test_parse_semver_accepts_seeded_generated_corpus(seed):
    for version in generate_valid_semver_corpus(seed=seed, count=160):
        parse_semver(version)


@pytest.mark.parametrize("seed", [2, 8, 34])
def test_parse_semver_rejects_seeded_invalid_mutations(seed):
    valid_versions = generate_valid_semver_corpus(seed=seed, count=64)
    for version in generate_invalid_semver_mutations(valid_versions, seed=seed):
        with pytest.raises(MlflowException, match="Invalid semantic version"):
            parse_semver(version)


@pytest.mark.parametrize(("lower", "higher"), PUBLIC_PRECEDENCE_PAIRS)
def test_compare_semver_matches_public_precedence_examples(lower, higher):
    lower_parsed = parse_semver(lower)
    higher_parsed = parse_semver(higher)

    assert compare_semver(lower_parsed, higher_parsed) == -1
    assert reference_compare_semver(lower_parsed, higher_parsed) == -1


def test_compare_semver_matches_spec_precedence_chain():
    parsed_chain = [parse_semver(version) for version in SPEC_PRECEDENCE_CHAIN]

    for lower, higher in zip(parsed_chain, parsed_chain[1:]):
        assert compare_semver(lower, higher) == -1
        assert reference_compare_semver(lower, higher) == -1


@pytest.mark.parametrize("seed", [3, 11, 29])
def test_compare_semver_matches_reference_on_seeded_corpus(seed):
    versions = generate_valid_semver_corpus(seed=seed, count=96)
    parsed_versions = {version: parse_semver(version) for version in versions}

    for left in versions:
        for right in versions:
            expected = reference_compare_semver(parsed_versions[left], parsed_versions[right])
            assert compare_semver(parsed_versions[left], parsed_versions[right]) == expected


@pytest.mark.parametrize("seed", [5, 17])
def test_compare_semver_sorts_seeded_corpus_like_reference(seed):
    versions = generate_valid_semver_corpus(seed=seed, count=160)
    parsed_versions = {version: parse_semver(version) for version in versions}

    compare_sorted = sorted(
        versions,
        key=cmp_to_key(
            lambda left, right: compare_semver(parsed_versions[left], parsed_versions[right])
        ),
    )
    reference_sorted = sorted(
        versions,
        key=cmp_to_key(
            lambda left, right: reference_compare_semver(
                parsed_versions[left], parsed_versions[right]
            )
        ),
    )

    assert compare_sorted == reference_sorted
