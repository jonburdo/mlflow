## SemVer Prerelease Cheat Sheet

### Valid prerelease syntax

A prerelease is the part after `-` in:

- `MAJOR.MINOR.PATCH-prerelease`

It must be:

- one or more identifiers
- separated by `.`
- each identifier contains only ASCII letters, digits, or `-`
- no empty identifiers
- if an identifier is purely numeric, it cannot have leading zeroes unless it is exactly `0`

### Valid examples

- `alpha`
- `beta`
- `rc.1`
- `alpha.1`
- `alpha.beta`
- `0`
- `0.3.7`
- `x.7.z.92`
- `--`
- `alpha-1`
- `0A.is.legal`

### Invalid examples

- ```
  ""
  ```
- `.alpha`
- `alpha.`
- `alpha..1`
- `alpha_beta`
- `01`
- `00`
- `rc.01`

## Comparison rules

Given the same core version, e.g. `1.0.0-*`:

### 1. No prerelease beats any prerelease

- `1.0.0-alpha < 1.0.0`

### 2. Split prerelease on `.`

- `alpha.1` -> `["alpha", "1"]`
- `alpha.beta` -> `["alpha", "beta"]`

### 3. Compare identifiers left to right

#### Numeric vs numeric

Compare numerically.

- `1 < 2`
- `2 < 10`

So:

- `alpha.2 < alpha.10`

#### Numeric vs non-numeric

Numeric is always lower.

- `1 < alpha`

So:

- `1.0.0-1 < 1.0.0-alpha`

#### Non-numeric vs non-numeric

Compare lexically in ASCII order.

- `alpha < beta`
- `alpha < alpha1`
- `rc12 < rc3`

That last one is important:

- `rc12` and `rc3` are single text identifiers, so they compare as strings.
- If you want numeric behavior, use `rc.12` and `rc.3`.

### 4. If all shared identifiers are equal, shorter list is lower

- `alpha < alpha.1`
- `alpha.1 < alpha.1.1`

## Canonical ordering example

```text
1.0.0-alpha
< 1.0.0-alpha.1
< 1.0.0-alpha.beta
< 1.0.0-beta
< 1.0.0-beta.2
< 1.0.0-beta.11
< 1.0.0-rc.1
< 1.0.0
```

## Tricky examples

- `1.0.0-alpha < 1.0.0-alpha1`
- `1.0.0-alpha < 1.0.0-alpha-1`
- `1.0.0-alpha < 1.0.0-alpha.1`
- `1.0.0-1 < 1.0.0-alpha`
- `1.0.0-rc12 < 1.0.0-rc3`
- `1.0.0-rc.3 < 1.0.0-rc.12`

## Build metadata

The part after `+`:

- `1.0.0-alpha+build.1`

Rules:

- valid identifiers are also dot-separated ASCII alnum/hyphen
- leading zeroes are allowed
- it does **not** affect SemVer precedence

So:

- `1.0.0-alpha+abc`
- `1.0.0-alpha+xyz`

are equal in SemVer precedence.

## Tiny regex-style summary

A prerelease is basically:

```text
identifier(.identifier)*
```

where each `identifier` is:

- `0`
- or a non-zero numeric identifier like `7`, `12`, `999`
- or any non-numeric/mixed identifier made from `[0-9A-Za-z-]` that is not purely numeric-with-leading-zeroes

## Rule of thumb

Use:

- `rc.1`, not `rc1`, if you want numeric ordering
- `01` is invalid
- `alpha..1` is invalid
- prerelease always sorts below the final release

If you want, I can also put this into a Markdown file in the repo as a reference note.
