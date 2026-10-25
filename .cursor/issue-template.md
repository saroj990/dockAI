# GitHub issue draft template

Use one file per issue under `issues/` (gitignored). Filename: short kebab-case slug, e.g. `issues/ollama-preflight-health.md`.

At the top of each draft:

```markdown
**GitHub title:** <same as H1, under 80 characters>
```

Copy the **GitHub title** into GitHub's title field. Copy everything from **What is the issue** through **Test cases** into the issue body.

---

## What is the issue

<!-- Problem or missing behavior. Who is affected. Expected behavior. Name modules/commands; no implementation steps. -->

## How to reproduce

<!-- Numbered steps, config/env if relevant, example commands -->

1.
2.
3.

## Acceptance criteria

- [ ] <!-- Observable outcome a reviewer can verify -->
- [ ] <!-- Failure mode or edge case -->
- [ ] <!-- Regression: behavior that must stay unchanged -->

## Test cases

File: `tests/test_<area>.py`

| Test | Asserts |
|------|---------|
| `test_<name>` | <!-- input/fixture → expected --> |

- Run: `pytest tests/test_<area>.py -q`
- Mock HTTP/Docker as in existing tests; use `@pytest.mark.integration` only when a real engine is required.
