"""
Manual live smoke test for the Agent Orchestration Layer.

This is NOT part of the automated test suite and was NOT run during
development -- the sandbox this project was built in has no outbound
network access, so the actual round-trip to api.anthropic.com could
not be verified. Run this yourself once, with a real key, before
relying on the agent for a demo:

    export LLM_PROVIDER=ollama   # or GROQ_API_KEY=... / GEMINI_API_KEY=... / ANTHROPIC_API_KEY=...
    cd backend
    python3 -m app.seed_gsi      # real Fukuoka data
    python3 -m tests.agent_live_smoke_test

Expected behavior: the agent should call find_shelter_or_need, then
get_shelter_state and/or calculate_urgency, then generate_recommendation,
and finally produce a plain-language summary citing the real numbers.
If anything about the request/response shape has drifted from what
llm_client.py assumes, this is where you'll see it -- check the error
message against https://docs.claude.com/en/api/messages.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.agent.orchestrator import run_agent


def main():
    from app.agent import llm_client
    print("Provider:", llm_client.provider())

    db.init_db(reset=False)

    prompts = [
        "Shelter A urgently needs water, can you check the situation and recommend a plan?",
        "What about the power situation at Shelter C?",
    ]
    conversation = None
    for prompt in prompts:
        print("\n" + "=" * 70)
        print("USER:", prompt)
        print("=" * 70)
        result = run_agent(prompt, conversation=conversation)
        if result.get("error"):
            print(f"ERROR [{result['error']}]: {result.get('message')}")
            sys.exit(1)
        for step in result["trace"]:
            if step["type"] == "tool_call":
                print(f"  -> calling {step['name']}({step['input']})")
            elif step["type"] == "tool_result":
                print(f"     result: {step['result']}")
            elif step["type"] == "assistant_text":
                print(f"  [agent says]: {step['text']}")
        print("\nFINAL:", result["final_message"])
        conversation = result["messages"]

    print("\n" + "=" * 70)
    print("If the numbers above match what /api/needs shows in the dashboard, it's working.")


if __name__ == "__main__":
    main()
