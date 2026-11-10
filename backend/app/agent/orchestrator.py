"""
Agent Orchestrator  —  spec section 173 ("Agent Orchestration Layer")
and 173.1 ("Example Agent Workflow").

This IS the diagram in spec 173.1:

    "Shelter A urgently needs water."
            |
    Call: getShelterState(A)  ->  missing quantity? -> ask for more info
    Call: calculateUrgency()  ->  Urgency = 8.9
    Call: generateCandidates() / calculateFeasibility() / calculateUtility()
    Call: rankPlans()
            |
    Send recommendation to coordinator

The loop below is a standard Anthropic tool-use loop: ask the model,
execute whatever tools it asks for against the REAL deterministic
engine, feed the results back, repeat until it stops calling tools.
"""
from . import tools as agent_tools
from .llm_client import call_claude, LlmConfigError, LlmRequestError

SYSTEM_PROMPT = """You are the DisasterOps coordination agent for a disaster-response \
shelter network. A human municipal coordinator is talking to you.

Rules you must follow exactly:
1. You must NEVER invent, estimate, or calculate an urgency, feasibility, or utility \
score yourself. Every number you state must come from a tool result. If you haven't \
called the relevant tool yet, call it before stating any score.
2. If a message names a shelter or resource in plain language (e.g. "Shelter A", \
"the water situation"), call find_shelter_or_need first to resolve it to an ID before \
calling any other tool.
3. You cannot approve, dispatch, or commit anything. You investigate and recommend; \
a human coordinator must approve any plan in the dashboard before a vehicle moves. \
If asked to "approve" or "send" something, explain that you'll prepare the \
recommendation for the coordinator to approve, not do it yourself.
4. Be concise. State the key numbers (urgency, ETA, feasibility, utility) plainly, \
explain the recommended plan's "why" in a sentence or two, and stop -- don't restate \
the full tool output.
5. If calculate_urgency returns status NEEDS_DATA, say plainly what's missing and \
recommend the coordinator request an updated shelter report; do not call \
generate_recommendation on an underspecified need.
"""


def run_agent(user_message, max_turns=6, conversation=None):
    """Runs the tool-calling loop for one user message.

    conversation: optional prior message list to continue a session;
    pass None to start fresh. Returns {trace, final_message, messages}
    where `messages` can be passed back in as `conversation` for a
    follow-up turn.
    """
    messages = list(conversation) if conversation else []
    messages.append({"role": "user", "content": user_message})
    trace = []

    for _ in range(max_turns):
        try:
            response = call_claude(messages, tools=agent_tools.TOOL_SCHEMAS, system=SYSTEM_PROMPT)
        except LlmConfigError as e:
            return {"trace": trace, "final_message": None, "error": "LLM_NOT_CONFIGURED", "message": str(e), "messages": messages}
        except LlmRequestError as e:
            return {"trace": trace, "final_message": None, "error": "LLM_REQUEST_FAILED", "message": str(e), "messages": messages}

        content = response.get("content", [])
        text_parts = [b["text"] for b in content if b.get("type") == "text"]
        tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]

        if text_parts:
            trace.append({"type": "assistant_text", "text": "\n".join(text_parts)})

        if not tool_use_blocks:
            messages.append({"role": "assistant", "content": content})
            return {"trace": trace, "final_message": "\n".join(text_parts), "messages": messages}

        messages.append({"role": "assistant", "content": content})
        tool_result_blocks = []
        for tb in tool_use_blocks:
            trace.append({"type": "tool_call", "name": tb["name"], "input": tb.get("input", {})})
            result = agent_tools.dispatch_tool(tb["name"], tb.get("input", {}))
            trace.append({"type": "tool_result", "name": tb["name"], "result": result})
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tb["id"],
                "content": _to_text(result),
            })
        messages.append({"role": "user", "content": tool_result_blocks})

    return {"trace": trace, "final_message": None, "error": "MAX_TURNS_EXCEEDED", "messages": messages}


def _to_text(result):
    import json
    return json.dumps(result)
