# s01: The Agent Loop

`[ s01 ] s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12`

> *"One loop & Bash is all you need"* -- one tool + one loop = an agent.
>
> **Harness layer**: The loop -- the model's first connection to the real world.

## Problem

A language model can reason about code, but it can't *touch* the real world -- can't read files, run tests, or check errors. Without a loop, every tool call requires you to manually copy-paste results back. You become the loop.

## Solution

```
+--------+      +-------+      +---------+
|  User  | ---> |  LLM  | ---> |  Tool   |
| prompt |      |       |      | execute |
+--------+      +---+---+      +----+----+
                    ^                |
                    |   tool_result  |
                    +----------------+
                    (loop until stop_reason != "tool_use")
```

One exit condition controls the entire flow. The loop runs until the model stops calling tools.

## How It Works

1. User prompt becomes the first message.

```python
messages.append({"role": "user", "content": query})
```

2. Send messages + tool definitions to the LLM.

```python
response = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "system", "content": SYSTEM}] + messages,
    tools=TOOLS,
    max_completion_tokens=4096,
)
```

3. Append the assistant response. If the model didn't call a tool, we're done.

```python
msg = response.choices[0].message
messages.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})
if not msg.tool_calls:
    return
```

4. Execute each tool call, append each result as a `tool` message. Loop back to step 2.

```python
for tool_call in msg.tool_calls:
    output = run_bash(json.loads(tool_call.function.arguments)["command"])
    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": output})
```

Assembled into one function:

```python
def agent_loop(query):
    messages = [{"role": "user", "content": query}]
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,
            max_completion_tokens=4096,
        )
        msg = response.choices[0].message
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})

        if not msg.tool_calls:
            return

        for tool_call in msg.tool_calls:
            output = run_bash(json.loads(tool_call.function.arguments)["command"])
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": output})
```

That's the entire agent in under 30 lines. Everything else in this course layers on top -- without changing the loop.

## What Changed

| Component     | Before     | After                          |
|---------------|------------|--------------------------------|
| Agent loop    | (none)     | `while True` + tool_calls check |
| Tools         | (none)     | `bash` (one tool)               |
| Messages      | (none)     | Accumulating list               |
| Control flow  | (none)     | `not msg.tool_calls`            |

## Try It

```sh
cd learn-claude-code
python agents/s01_agent_loop.py
```

1. `Create a file called hello.py that prints "Hello, World!"`
2. `List all Python files in this directory`
3. `What is the current git branch?`
4. `Create a directory called test_output and write 3 files in it`
