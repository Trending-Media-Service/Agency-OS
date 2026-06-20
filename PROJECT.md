# Project: Agency-OS PR Merging and Test Hygiene

## Architecture
- **Control Plane**: FastAPI web server that manages connections, brands, and infrastructure recipes.
- **Recipes Engine**: Catalog of experimental and production infrastructure templates (Terraform + YAML) under the `recipes/` directory.
- **Background Tasks**: Periodic tasks (such as token rotation and brand graph sensing) that run asynchronously to maintain environment state.
- **Auditing & Governance**: Strict state machine enforcing that all modifications to state models flow through governed, audited Ops.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 1 | PR Monitoring & Merging (R1) | Resolve TypeScript/linter build errors on PR #182 and PR #183, pass remote CI checks, squash-merge both PRs into `main`, and cleanly restore stashed changes. | None | **DONE** |
| 2 | Resolve Issue #119 - Test Hygiene & Hardening (R2) | Implement 100% sandboxed test execution for recipe promotion (Issue #119) and remediate all 5 security/integrity audit findings (sibling prefix bypass, secret leak in logs, non-governed writes in `sense.py`, whitelist cheating in `test_no_silent_writes.py`). | None | **IN_PROGRESS** |

## Interface Contracts
### /recipes/promote Endpoint ↔ Version Control
- **Request Body**: `RecipePromoteIn` (`recipe_name` match `^[a-zA-Z0-9_-]+$`, `version` match `^[a-zA-Z0-9_.-]+$`).
- **Functionality**: Resolves experimental path, verifies containment under `RECIPES_ROOT` (directory boundary enforced), copies recipe to production, commits to git via `subprocess.run` (mocked in tests).
- **Responses**:
  - `200 OK` on successful promotion.
  - `400 Bad Request` on path traversal, invalid characters, or missing files.
  - `404 Not Found` if experimental recipe does not exist.

## Code Layout
- `control-plane/app/main.py`: Main routes, including `/recipes/promote`.
- `control-plane/app/tasks/sense.py`: Background brand graph sense task.
- `control-plane/app/adapters/manage.py`: `ManageAdapter` containing connection operations, backing the new governed `manage.brand.sense` Op.
- `control-plane/app/services/secrets.py`: Mock secret manager client with masked logging.
- `control-plane/tests/test_kernel.py`: Main operational tests (sandboxed).
- `control-plane/tests/test_no_silent_writes.py`: Direct write AST checks (strictness restored).
- `control-plane/tests/test_path_traversal_challenge.py`: Path traversal validation tests.
