# Docker AI Agent CLI — Context and Scope

## 1. Project Context

Build a command-line AI agent that lets a user interact with Docker in natural language, as if talking to a person.

Instead of remembering Docker commands and flags, a user can ask questions such as:

- “Show me the running containers.”
- “Show me the last 25 lines of logs for api-server.”
- “My container keeps restarting. What could be the issue?”
- “Show container ID, status, and name in a table.”
- “Find containers with `flink` in their name.”
- “Stop api-server.”

The agent interprets the request, chooses from a controlled set of Docker tools, retrieves or changes Docker state, and explains the result.

**Core principle:** the LLM interprets intent and explains results; Docker is the source of truth for container state, logs, timestamps, and operation outcomes.

## 2. Goals

1. Make common Docker inspection and troubleshooting tasks accessible through natural language.
2. Support both an interactive chat session and one-shot commands.
3. Return accurate results grounded in Docker responses.
4. Format results clearly in terminal tables and readable summaries.
5. Make troubleshooting evidence-based: inspect state and logs before suggesting likely causes.
6. Require explicit confirmation before destructive or disruptive operations.
7. Be easy to test, debug, and extend without starting with a complex multi-agent framework.

## 3. Intended Users and Environment

- Developers and operators who use Docker and want a faster natural-language interface.
- Initial target: a local CLI connecting to a Docker Engine available to the user.
- Initial LLM provider: Ollama, with the provider integration kept replaceable where practical.
- The user must already have permission to access the target Docker Engine.

Remote Docker access, multi-user access, and production fleet management are not part of the initial MVP.

## 4. Interaction Modes

### 4.1 One-shot mode

Run one request per invocation:

```bash
dockai "show running containers"
dockai "show the last 25 lines of api-server logs"
dockai "find containers named flink"
```

Each invocation is independent by default. Persistent history can be added later if needed.

### 4.2 Interactive chat mode

Start a session and ask follow-up questions:

```text
$ dockai chat
You: Show containers that are restarting.
Agent: I found one restarting container: flink-jobmanager.
You: Show its recent logs.
Agent: [Shows the latest 100 log lines.]
You: What might be causing it?
Agent: [Explains likely causes supported by the observed state and logs.]
```

The session may retain context while it is running. Persistent memory across separate sessions is out of scope for the MVP.

## 5. Functional Scope

### 5.1 Read-only container operations

The MVP must support:

- List running containers.
- List all containers, including stopped containers.
- Show container name, ID, status, image, and uptime/start time as applicable.
- Inspect a container's state and useful metadata.
- Retrieve container logs.
- Search containers by a name keyword.
- Identify containers that are restarting or have exited.
- Show restart count and relevant state information when available.

### 5.2 Log behavior

- Default: show the latest **100 lines**.
- If the user specifies a line count, honor that count.
- If the user asks for full logs, retrieve all logs available through Docker's logging interface, subject to output safeguards.
- Make it clear when output is truncated or limited.
- Handle containers with no logs, unavailable containers, and Docker logging errors without inventing output.
- “Full logs” means logs retained and accessible from Docker; it does not guarantee logs that have already been rotated or discarded.

### 5.3 Uptime behavior

- For running containers, calculate elapsed time from Docker's reported start time.
- For stopped containers, show the last start time and stopped/exited state instead of describing them as currently running.
- Label the result clearly and avoid confusing container creation time with uptime.

### 5.4 Natural-language troubleshooting

For a request such as “My container is restarting; what could be the issue?” the agent should:

1. Identify matching restarting containers, asking for clarification if the target is ambiguous.
2. Retrieve relevant state, restart count, exit information, and recent logs.
3. Summarize observed facts.
4. Explain plausible causes supported by that evidence.
5. Clearly distinguish facts from hypotheses.
6. Suggest safe next diagnostic steps.

The agent must not claim that a cause is confirmed unless the available evidence supports that conclusion. It must report when evidence is insufficient.

### 5.5 Formatted output

Support readable terminal tables. At minimum, a user should be able to request a table containing:

| Column | Meaning |
|---|---|
| ID | Container ID, abbreviated by default if appropriate |
| Name | Container name |
| Status | Current Docker status |
| Uptime | Elapsed running time, where applicable |

Allow the agent to select sensible columns from a natural-language request. Keep output stable and readable in terminals.

### 5.6 Name search

- Search container names using a requested keyword.
- Case-insensitive matching should be the default.
- State whether the search includes running containers only or all containers.
- Prefer searching all containers when the user does not specify; make the scope visible in the response.
- If several matches could be the target of an operation, ask the user to select one.

### 5.7 State-changing operations

The MVP may support:

- Start a container.
- Stop a container.
- Restart a container.

Removal and pruning operations are excluded from the initial MVP unless explicitly added after the core safety workflow is tested.

## 6. Mandatory Safety Rules

### 6.1 Controlled tools only

- The LLM must not execute arbitrary shell commands.
- The LLM must not produce a command string that is passed unchecked to a shell.
- It may select only from predefined application tools with validated parameters.
- Use the Docker SDK where practical rather than shelling out to the Docker CLI.

### 6.2 Confirmation for disruptive actions

Before a stop, restart, or other disruptive action, the agent must:

1. Resolve the exact container target.
2. Show its name, ID, and current state.
3. Explain the expected effect and relevant risk.
4. Ask for explicit confirmation.
5. Execute only after an unambiguous affirmative response.
6. Verify the resulting state and report the actual outcome.

A missing, ambiguous, or negative response must not trigger execution. If multiple containers match, ask which container the user means before asking for final confirmation.

For any future removal or pruning feature, explain what will be deleted and its scope; require explicit confirmation. Destructive actions should not be silently inferred from vague instructions.

### 6.3 Tool-result integrity

- Never report success before Docker confirms the operation.
- Never invent container IDs, states, log lines, timestamps, or error details.
- Validate tool arguments before execution.
- Handle timeouts, unavailable Docker Engine, permission failures, missing containers, and LLM/tool-call failures explicitly.
- Do not retry a state-changing operation blindly when the outcome is uncertain; inspect state first.

### 6.4 Access and permissions

Docker access can grant powerful host-level control. Run the agent only with the Docker permissions it needs, protect Docker socket access, and do not expose an unauthenticated remote Docker API. Do not attempt to bypass existing user or host permissions.

## 7. High-Level Architecture

```text
User
  |
  v
CLI interface (Typer)
  |
  v
Conversation / request handler
  |
  v
LLM provider adapter (initially Ollama)
  |
  v
Tool selection and parameter validation
  |
  v
Safety and confirmation layer
  |
  v
Docker tool layer (Docker SDK for Python)
  |
  v
Docker Engine
  |
  v
Structured results returned to the agent
  |
  v
Readable response / Rich terminal tables
```

The LLM should receive concise, structured tool results rather than unnecessary raw data. For log analysis, pass only the relevant log output and state information required for the user's request.

## 8. Suggested Technology Stack

- **Language:** Python
- **CLI framework:** Typer
- **Terminal tables and formatting:** Rich
- **Docker access:** Docker SDK for Python
- **Initial LLM:** Ollama, using a model verified to support the required tool-calling behavior
- **Tests:** pytest, with mocked Docker responses and controlled integration tests

Keep the LLM provider and Docker tool layer separated so either can be changed independently.

## 9. Acceptance Test Scenarios

The MVP is not complete until these behaviors are tested.

| ID | Request / scenario | Expected result |
|---|---|---|
| AT-01 | “Show running containers.” | Lists only running containers, using live Docker data. |
| AT-02 | “Show logs of api-server.” | Shows the latest 100 lines by default. |
| AT-03 | “Show the last 25 lines of api-server logs.” | Requests and displays 25 lines. |
| AT-04 | “Show full logs of api-server.” | Retrieves all currently available logs subject to documented output safeguards. |
| AT-05 | “My container is restarting. What could be the issue?” | Inspects state, restart count, and recent logs; explains evidence and hypotheses. |
| AT-06 | “Show me uptime of my containers.” | Shows elapsed running time for running containers and accurate state for stopped ones. |
| AT-07 | “Show ID, status, and name in a table.” | Displays those fields in a readable table. |
| AT-08 | “Find containers named flink.” | Returns case-insensitive keyword matches and makes search scope clear. |
| AT-09 | “Stop api-server.” | Explains the impact and asks for confirmation before stopping. |
| AT-10 | User answers “no” or gives no clear confirmation. | Does not execute the action. |
| AT-11 | Several containers match the requested action. | Asks the user to select the exact target. |
| AT-12 | Container does not exist or Docker is unavailable. | Reports the real error clearly; does not fabricate success. |
| AT-13 | LLM returns invalid tool arguments or fails to call a tool. | Validates/rejects the call and reports failure safely. |
| AT-14 | Stop/restart succeeds or fails. | Checks Docker state and reports the observed outcome. |
| AT-15 | Very large or empty logs. | Handles the case safely and explains limits or absence of output. |

Use mocks for routine automated tests. Run integration tests against disposable test containers, not production workloads.

## 10. Non-Functional Requirements

- **Correctness:** Operational facts come from Docker, not model guesses.
- **Safety:** Explicit confirmation and validated targets for disruptive actions.
- **Reliability:** Clear handling of Docker and LLM failures.
- **Usability:** Concise answers, readable tables, and useful error messages.
- **Testability:** Keep request interpretation, tools, safety checks, and presentation separable.
- **Debuggability:** Provide optional diagnostic logging for tool selection, validated arguments, tool execution, and failures; avoid logging secrets.
- **Performance:** Keep routine read-only operations responsive and limit unnecessary LLM calls.
- **Privacy:** Send only the minimum information needed to the configured LLM. If using a local Ollama model, keep inference local unless the chosen setup routes data elsewhere.

## 11. Out of Scope for the Initial MVP

- Kubernetes, container orchestration across clusters, and multi-host fleet management.
- Arbitrary host shell execution.
- Automatically editing application files, Dockerfiles, or Compose files.
- Automatically fixing or redeploying broken applications.
- Autonomous remediation without user approval.
- Container removal, image deletion, volume deletion, and broad prune commands.
- Persistent memory across sessions.
- Web UI, multi-user authentication, team audit portal, and role-based access control.
- Advanced metrics, alerting, and continuous monitoring.

These may be considered after the MVP has reliable tool execution, safety behavior, and test coverage.

## 12. Implementation Plan

### Phase 1 — Docker foundation
- Set up the Python project and CLI.
- Connect to Docker through the SDK.
- Implement and test read-only container operations.
- Add log defaults, uptime calculation, keyword search, and Rich tables.

### Phase 2 — LLM integration
- Connect Ollama through a provider adapter.
- Define tool schemas and argument validation.
- Implement the tool-calling loop.
- Verify that invalid or failed tool calls never produce fabricated results.

### Phase 3 — Interactive chat
- Add `dockai chat`.
- Support follow-up requests within a session.
- Handle references such as “that container” only when the intended target is unambiguous.

### Phase 4 — Safe state-changing operations
- Add start, stop, and restart.
- Implement target resolution, impact explanation, explicit confirmation, and post-action verification.
- Test negative, ambiguous, and failed-operation paths.

### Phase 5 — Hardening
- Complete the acceptance tests.
- Test with disposable containers.
- Add timeouts, useful diagnostics, documentation, and installation instructions.

## 13. Definition of Done

The initial MVP is done when:

- Both one-shot and interactive modes work.
- All acceptance tests pass.
- Log defaults and requested line counts are honored.
- Restart troubleshooting is evidence-based and appropriately qualified.
- Tables, uptime, and keyword searches use real Docker data.
- State-changing operations cannot run without explicit confirmation.
- Errors and failed tool calls are reported honestly.
- No LLM output is executed as an unchecked shell command.
- The project includes setup instructions, examples, and tests.

## 14. Key Product Decision

Build a **small, controlled tool-using agent**, not a general-purpose autonomous agent. Begin with dependable Docker inspection, then add LLM tool calling, conversation, and confirmed state changes. Reliability and safety take priority over the number of tools.
