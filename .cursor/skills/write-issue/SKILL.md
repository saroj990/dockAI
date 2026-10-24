---
name: write-issue
description: >-
  Draft a software issue with a title, description, success criteria, and a
  testing plan that names unit tests. Use when the user asks for an issue,
  a ticket, a bug report, a feature spec, or to address, implement, or fix
  an issue in this repo.
---

# Write an issue

When the user asks for an issue, reply with the issue only. Do not change code until they ask to address it.

When they ask to address, implement, or fix an issue, use the issue already in the conversation. If none exists, draft it first, then implement it in the same turn.

Follow [.cursor/rules/github-issues.mdc](../../rules/github-issues.mdc) and [.cursor/issue-template.md](../../issue-template.md). Save drafts under `issues/<slug>.md` (gitignored).

## Draft

Ground the issue in the current code. Read the files the change would touch before writing acceptance criteria or tests. Name real modules, functions, and `tests/test_*.py` files.

Use this structure:

```markdown
**GitHub title:** <imperative title, under 80 characters>

## What is the issue
What is wrong or missing, who is affected, and the expected behavior.
Include the relevant module or command. Leave out implementation steps.

## How to reproduce
1. …
2. …
3. …

## Acceptance criteria
- [ ] Observable outcome a reviewer can check without reading the diff
- [ ] Edge case or failure mode that must hold
- [ ] Behavior that must stay unchanged

## Test cases
File: `tests/test_<area>.py`

| Test | Asserts |
|------|---------|
| `test_<behavior>` | <input or fixture> → <expected result> |

- Reuse `make_container` and `mock_client` from `tests/conftest.py` when the code talks to Docker.
- Mock the Docker client. Add `@pytest.mark.integration` only when a test needs a real engine.
- One test per acceptance criterion, plus tests for empty input, errors, and unchanged behavior.
- Run: `pytest tests/test_<area>.py -q`
```

Rules for the draft:

- Title states the outcome, not the task type. Prefer `Show stopped containers with exited status` over `Add feature for containers`.
- Acceptance criteria are checks, not tasks. Prefer `dockai ps includes exited containers` over `Update the ps command`.
- **How to reproduce** must be concrete commands and config, not vague steps.
- The test section names pytest functions and what each one asserts. Do not paste full test code in the issue.
- Do not invent files, flags, or commands that are not in the repo.

## Address

1. Implement only what the acceptance criteria require.
2. Add the unit tests named in the test cases section. Match existing tests: pytest, `tests/test_*.py`, fixtures from `tests/conftest.py`.
3. Run `pytest tests/test_<area>.py -q`. If it fails, fix the code or the test and run it again.
4. Report which acceptance criteria the tests cover and the pytest result.

## Example

User: issue for uptime showing a dash when the container has not started

```markdown
**GitHub title:** Show a dash when container uptime has no start time

## What is the issue
`compute_uptime` in `src/dockai/uptime.py` can receive Docker's zero timestamp (`0001-01-01T00:00:00Z`) for a container that never started. Callers need a stable empty value instead of a parsed datetime or a crash. Running containers with a real `StartedAt` must still report elapsed time.

## How to reproduce
1. Inspect or list a container that never started (zero `StartedAt` in Docker state).
2. Render uptime via the code path that calls `compute_uptime`.
3. Observe incorrect display or parse error instead of `-`.

## Acceptance criteria
- [ ] A zero Docker timestamp yields no start time and uptime displays `-`
- [ ] A running container with a real start time still reports elapsed time
- [ ] A stopped container is reported as stopped, not as running uptime

## Test cases
File: `tests/test_uptime.py`

| Test | Asserts |
|------|---------|
| `test_parse_docker_time_zero_is_none` | `parse_docker_time("0001-01-01T00:00:00Z")` is `None` |
| `test_compute_uptime_running` | status `running` from a fixed `now` returns kind `uptime` and the elapsed string |
| `test_compute_uptime_stopped_not_described_as_running` | status `exited` returns kind `stopped` |

- No Docker client; call `compute_uptime` and `parse_docker_time` directly.
- Run: `pytest tests/test_uptime.py -q`
```
