"""Phase 1.7 Task 1 spike — verify MaaS reachability + tool calling.

Checks that the base URL works and that the two candidate chat models are
reachable AND return OpenAI tool_calls:
  - google/gemma-4-31b-it
  - qwen/qwen3-5-27b

Prints the FULL raw response for each so you can inspect it. Reads creds from
settings (.env): AGENTBASE_LLM_BASE_URL / AGENTBASE_LLM_API_KEY. Never prints the key.

Run it yourself:  venv/bin/python scripts/spike_toolcalling.py
(No PYTHONPATH needed — the script adds src/ to sys.path.)
"""
from __future__ import annotations

import sys
from pathlib import Path

# src-layout: make `eventbuddy` importable without setting PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai import OpenAI  # noqa: E402

from eventbuddy.config import settings  # noqa: E402

# The two models to verify (override on the command line: `... spike_toolcalling.py m1 m2`).
MODELS = sys.argv[1:] or ["google/gemma-4-31b-it", "qwen/qwen3-5-27b"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a new event with a name and an optional list of member emails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The event name"},
                    "member_emails": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Emails of members to invite",
                    },
                },
                "required": ["name"],
            },
        },
    }
]

PROMPT = [
    {"role": "system", "content": "You are EventBuddy. Use tools when the user wants an action."},
    {"role": "user", "content": "Create an event called Demo Day with members a@x.com and b@x.com"},
]

SEP = "=" * 72


def main() -> None:
    base = settings.agentbase_llm_base_url
    key = settings.agentbase_llm_api_key
    print(SEP)
    print(f"base_url : {base or 'EMPTY'}")
    print(f"api_key  : {f'set (len={len(key)})' if key else 'EMPTY'}")
    print(f"models   : {MODELS}")
    print(SEP)
    if not base or not key:
        print("✗ Missing creds. Set AGENTBASE_LLM_BASE_URL / AGENTBASE_LLM_API_KEY in .env.")
        sys.exit(1)

    client = OpenAI(base_url=base, api_key=key)
    results: dict[str, str] = {}

    for model in MODELS:
        print(f"\n### MODEL: {model}\n" + "-" * 72)
        try:
            resp = client.chat.completions.create(
                model=model, messages=PROMPT, tools=TOOLS, tool_choice="auto"
            )
        except Exception as e:
            results[model] = f"UNREACHABLE ({type(e).__name__})"
            print(f"✗ request failed: {type(e).__name__}: {str(e)[:300]}")
            continue

        # Full raw response for inspection.
        print("RAW RESPONSE:")
        print(resp.model_dump_json(indent=2))

        # Parsed summary.
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        print("\nPARSED:")
        print(f"  finish_reason : {resp.choices[0].finish_reason}")
        print(f"  content       : {msg.content!r}")
        if tool_calls:
            for i, tc in enumerate(tool_calls):
                print(f"  tool_call[{i}] : {tc.function.name}({tc.function.arguments})")
            results[model] = "REACHABLE + TOOL_CALLS ✓"
        else:
            results[model] = "REACHABLE but NO tool_calls"

    print("\n" + SEP)
    print("VERDICT")
    for model, r in results.items():
        print(f"  {model:28s} -> {r}")
    print(SEP)


if __name__ == "__main__":
    main()
