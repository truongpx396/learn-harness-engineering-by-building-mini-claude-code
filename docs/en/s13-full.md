# s13: The Full Agent (Capstone)

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 > [ s13 ]`

> *"Every mechanism in a single cockpit — the model sees one coherent interface"* — tools compose, loops nest, and the harness disappears.
>
> **Harness layer**: Integration — all s01–s12 mechanisms unified into one runnable reference agent.

## Problem

By s12, each mechanism works in isolation: the agent loop, tool dispatch, todos, subagents, skills, context compression, file tasks, background jobs, messaging, shutdown/plan protocols, and worktree isolation. But they were never run together. In a real session the agent must:

- Manage its own context budget while executing long multi-step plans.
- Delegate sub-problems to subagents and teammates in parallel.
- Receive background results and inbox messages between LLM calls, without losing state.
- Apply shutdown and plan-approval handshakes correctly inside a shared event loop.
- Use skill documents to handle specialised domains without bloating the system prompt.

Combining these without a clear seam order leads to races (background drain vs. inbox drain), token bloat (skills injected every turn), and silent tool failures. `s_full.py` is the reference that shows the correct composition order.

## Solution

```
Before every LLM call:
  1. microcompact   (clear old tool results > 3 turns old)
  2. auto-compact   (summarise when tokens > threshold)
  3. drain bg       (append background results to messages)
  4. drain inbox    (append lead inbox to messages)

LLM call -> tool dispatch:
  ┌─────────────────────────────────────────────────────────┐
  │  bash │ read_file │ write_file │ edit_file │ TodoWrite  │
  │  task (subagent) │ load_skill │ compress   │            │
  │  background_run  │ check_background                     │
  │  task_create │ task_get │ task_update │ task_list       │
  │  spawn_teammate │ list_teammates                        │
  │  send_message │ read_inbox │ broadcast                  │
  │  shutdown_request │ plan_approval                       │
  │  idle │ claim_task                                      │
  └─────────────────────────────────────────────────────────┘

After every tool batch:
  - Todo nag if open items exist and >= 3 rounds without TodoWrite
  - If compress tool called: run auto_compact, return to REPL
```

## How It Works

### 1. Composition order inside the loop

The loop runs three pipeline steps before every LLM call to keep context clean and messages up to date:

```python
def agent_loop(messages):
    while True:
        microcompact(messages)                        # s06 – trim old tool results
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            messages[:] = auto_compact(messages)      # s06 – summarise
        notifs = BG.drain()                           # s08 – background results
        if notifs:
            messages.append(...)
        inbox = BUS.read_inbox("lead")                # s09/s10 – teammate messages
        if inbox:
            messages.append(...)
        response = client.chat.completions.create(...)
        ...
```

Order matters: compress first (shrinks context), then inject new data (background + inbox). Injecting before compressing would waste tokens on content that may be summarised away.

### 2. Tool handler table

All 23 tools are registered in a flat `TOOL_HANDLERS` dict. The loop is tool-agnostic — it calls `TOOL_HANDLERS[name](**args)` for every tool call returned by the model:

```python
TOOL_HANDLERS = {
    "bash":             lambda **kw: run_bash(kw["command"]),
    "task":             lambda **kw: run_subagent(kw["prompt"], kw.get("agent_type", "Explore")),
    "load_skill":       lambda **kw: SKILLS.load(kw["name"]),
    "background_run":   lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
    "spawn_teammate":   lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"]),
    "plan_approval":    lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], ...),
    ...  # 23 total
}
```

Adding a new tool requires: (1) a handler entry here, (2) a JSON schema entry in `TOOLS`, (3) nothing else.

### 3. Subagents (s04)

`task` spawns a synchronous sub-loop with its own message history and a restricted tool set (`bash`, `read_file`, and optionally `write_file`/`edit_file`):

```python
def run_subagent(prompt, agent_type="Explore"):
    sub_msgs = [{"role": "user", "content": prompt}]
    for _ in range(30):
        resp = client.chat.completions.create(model=MODEL, messages=sub_msgs, tools=sub_tools)
        ...
    return last_msg.content  # summary returned to lead
```

The lead's context receives only the final summary. Long exploration stays isolated.

### 4. Teammates (s09/s11)

`spawn_teammate` starts a background thread running its own agent loop. The thread idles when it has no work, auto-claims unclaimed tasks from `.tasks/`, and wakes on inbox messages:

```python
# Idle phase: poll every POLL_INTERVAL seconds
for _ in range(IDLE_TIMEOUT // POLL_INTERVAL):
    time.sleep(POLL_INTERVAL)
    inbox = self.bus.read_inbox(name)
    if inbox:
        resume = True; break
    unclaimed = [t for t in tasks if t["status"] == "pending" and not t["owner"]]
    if unclaimed:
        self.task_mgr.claim(unclaimed[0]["id"], name)
        resume = True; break
```

### 5. Shutdown and plan-approval handshakes (s10)

Both protocols use a `request_id` to correlate request with response across the message bus:

```python
def handle_shutdown_request(teammate):
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"
```

The teammate thread checks inbox for `shutdown_request` type and exits its loop cleanly. `plan_approval` follows the same pattern but routes `plan_approval_response` back via the bus.

### 6. Todo nag (s03)

After each tool batch, the loop counts rounds since the last `TodoWrite` call. If open todos exist and the count reaches 3, it appends a reminder:

```python
rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
if TODO.has_open_items() and rounds_without_todo >= 3:
    messages.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"})
```

### 7. REPL commands

| Command    | Action                                 |
|------------|----------------------------------------|
| `/compact` | Manually trigger `auto_compact`        |
| `/tasks`   | Print the file-task board              |
| `/team`    | Print teammate status                  |
| `/inbox`   | Read and drain the lead inbox          |
| `q / exit` | Quit                                   |

## What Changed From s12

| Component          | Before (s12)                        | After (s13 / s_full)                              |
|--------------------|-------------------------------------|---------------------------------------------------|
| Scope              | Worktree isolation only             | All mechanisms integrated                         |
| Context management | Not present                         | microcompact + auto-compact in loop               |
| Background jobs    | Not present                         | Drain before every LLM call                       |
| Inbox              | Not present                         | Drain before every LLM call                       |
| Teammates          | Separate session (s09)              | Always available via `spawn_teammate`             |
| Skills             | Separate session (s05)              | Always available via `load_skill`                 |
| Todo tracking      | Not present                         | Nag reminder after 3 rounds without `TodoWrite`   |
| Tool count         | ~10 (s12)                           | 23 (all mechanisms)                               |

## Try It

```sh
cd learn-claude-code
source .venv/bin/activate

python3 agents/s_full.py          # resume previous session state
python3 agents/s_full.py --clean  # wipe .tasks, .team, .worktrees, .transcripts and start fresh
```

Inside the REPL, `/reset` does the same wipe mid-session without restarting.

**Step-by-step warm-up** (one prompt each):

1. `Create tasks for "write tests" and "update docs", then list tasks.`
2. `Spawn a teammate named "writer" with role "docs" to handle documentation tasks.`
3. `Run "sleep 2 && echo done" in the background, then check its status.`
4. `Load the agent-builder skill and summarise it.`
5. `Send a message to "writer" asking for a status update, then read your inbox.`
6. `Compact the context with /compact, then list teammates and tasks.`
7. `Request shutdown of "writer".`

---

**Full-surface stress prompt** — the agent chooses all tools on its own, but the specialists and isolation method are named explicitly to prevent hallucination. The prompt is saved to [docs/en/s13-full_final_prompt.txt](s13-full_final_prompt.txt) to avoid shell quoting issues with multi-line input.

Run it by piping the file directly into the agent:

```sh
cd learn-claude-code
source .venv/bin/activate

# fresh run (wipes previous state)
python3 agents/s_full.py --clean < docs/en/s13-full_final_prompt.txt

# or resume existing state
python3 agents/s_full.py < docs/en/s13-full_final_prompt.txt
```

Alternatively, use a heredoc to avoid the file entirely:

```sh
python3 agents/s_full.py --clean << 'EOF'
$(cat docs/en/s13-full_final_prompt.txt)
EOF
```
