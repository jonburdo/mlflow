# Conflict Resolution Reference

> **Note:** File paths below reflect the codebase as of v3.13.0. Upstream may rename or split files between releases — use `find` or `git diff` to locate the current path if a listed file is missing.

**Priority order:**

1. **Keep ODH customizations** — feature flags, module federation, PatternFly overrides, Konflux configs, gateway disable decorator, `onWorkspaceChange`
2. **Accept upstream renames/refactors** — function renames, new parameters, API changes
3. **Merge when both sides add** — imports, env vars, i18n entries, route definitions, webpack config functions
4. **Remove upstream-only CI** — Databricks tests, upstream-specific workflows
5. **For lock files** — take ODH's `exclude-newer-span`, accept upstream deps
6. **When in doubt** — check `git show upstream/master:<file>` for the intended final state

## Conflict type reference

Different git conflict types require different handling. Read `git status` carefully before resolving.

**`CONFLICT (modify/delete)`** — ODH deleted a file, upstream modified it.

- For upstream CI workflows (`.github/workflows/`): `git rm` — ODH intentionally removes these.
- For any other file type: investigate before deleting. The file may still be needed.

**`CONFLICT (rename/delete)`** — ODH deleted the old path, upstream renamed the file to a new path.

- Do NOT `git rm` the renamed file. Upstream reorganized the code; the renamed file is still needed.
- Keep the renamed version. Only the old path should be gone.
- Common for dev tooling files that upstream reorganizes between releases.

**Content conflicts in test files** — After resolving, verify ALL references to changed values are consistent within the file. Squashing can merge changes from multiple commits unevenly — some test functions get updated while others in the same file keep the old values.

## File-by-file patterns

**Scaffolding commit:**

| File                                      | Resolution                                                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `.github/workflows/*.yml` (modify/delete) | ODH deletes upstream workflows (approval, autoformat, cross-version-tests, slow-tests, helm, etc.). `git rm` all.  |
| `.github/workflows/master.yml`            | Remove Databricks-specific test steps.                                                                             |
| `pyproject.toml` `[tool.uv]`              | Keep ODH's `exclude-newer = "P14D"` and extra `exclude-newer-package` entries. Take upstream's `required-version`. |
| `uv.lock`                                 | Take ODH's `exclude-newer-span = "P14D"`.                                                                          |

**UI commit:**

| File                                      | Resolution                                                                                                                                                                            |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mlflow/environment_variables.py`         | Keep both upstream's new vars and ODH's `MLFLOW_ENABLE_ASSISTANT` / `MLFLOW_ENABLE_AI_GATEWAY`.                                                                                       |
| `mlflow/server/handlers.py`               | Keep ODH's `_disable_gateway` decorator. Accept upstream function renames.                                                                                                            |
| `mlflow/server/js/craco.config.js`        | Keep both webpack config functions (upstream's + ODH's `suppressAutoprefixerWarnings`).                                                                                               |
| `src/MlflowRouter.tsx`                    | Keep upstream route imports + ODH's `shouldEnableAIGateway()` wrapper on gateway routes.                                                                                              |
| `src/common/components/MlflowSidebar.tsx` | Keep upstream imports + ODH's `isAssistantEnabled`. Also check `MlflowSidebarGatewayItems.tsx` and `MlflowSidebarWorkflowSwitch.tsx` — upstream may split or refactor sub-components. |
| `src/common/forms/validations.ts`         | Keep ODH's simplified `.catch(() => callback(undefined))`. Remove dead `isResourceDoesNotExistError` and unused `ErrorCodes` import.                                                  |
| `.../header/ExperimentViewHeader.tsx`     | Keep imports from both sides. Full path: `src/experiment-tracking/components/experiment-page/components/header/`.                                                                     |
| `src/lang/default/en.json`                | Keep entries from both sides in alphabetical order. Then run `yarn i18n` in Phase 4 to prune orphans.                                                                                 |
| `src/workspaces/utils/WorkspaceUtils.ts`  | Keep both upstream's `useSyncExternalStore` pattern AND ODH's `onWorkspaceChange`. Both listener sets must be notified in `setActiveWorkspace`.                                       |

All `src/` paths above are relative to `mlflow/server/js/`.
