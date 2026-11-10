// AI Agent chat (spec section 173.1 "Example Agent Workflow"), made
// visible: the coordinator types a plain-language message, and we
// render the actual tool-call trace as it comes back, not just a
// final answer -- so it's clear this is an agent calling real
// deterministic tools, not a chatbot guessing numbers.

let agentConversation = null;

async function renderCoordinatorAgent(params, container) {
  container.innerHTML = `
    <div class="eyebrow">Operations</div>
    <h1 class="section-heading mb-16">AI Agent</h1>
    <p class="small muted mb-16">
      Talk to the DisasterOps agent the way a coordinator would (spec section 173.1). It resolves what you mention
      to real IDs, calls the same deterministic Urgency / Feasibility / Utility engines as the dashboard, and explains
      the result — it can recommend a plan but cannot approve or dispatch one; that still requires a human in the
      <a href="#/coordinator/needs" style="color:var(--accent);">Active Needs</a> screen.
    </p>

    <div class="card mb-16">
      <div class="flex gap-8 mb-12" style="flex-wrap:wrap;">
        <button class="btn example-prompt" data-prompt="Shelter A urgently needs water, can you check the situation and recommend a plan?">"Shelter A urgently needs water"</button>
        <button class="btn example-prompt" data-prompt="What's the power situation at Shelter C?">"Power situation at Shelter C?"</button>
        <button class="btn example-prompt" data-prompt="Which shelter has the most urgent unmet need right now?">"Most urgent need right now?"</button>
      </div>
      <form id="agent-form" class="flex gap-8">
        <input type="text" id="agent-input" placeholder="Ask the agent about a shelter or need…" style="flex:1;padding:10px 12px;border-radius:6px;border:1px solid var(--line);background:#ffffff;color:var(--ink-200);" />
        <button type="submit" class="btn btn-primary" id="agent-send-btn">Send</button>
        <button type="button" class="btn" id="agent-reset-btn">New conversation</button>
      </form>
    </div>

    <div id="agent-transcript"></div>
  `;

  qs('agent-form').addEventListener('submit', (e) => { e.preventDefault(); sendAgentMessage(qs('agent-input').value); });
  qs('agent-reset-btn').addEventListener('click', () => {
    agentConversation = null;
    qs('agent-transcript').innerHTML = '';
    toast('Started a new conversation', 'success');
  });
  document.querySelectorAll('.example-prompt').forEach((btn) => {
    btn.addEventListener('click', () => sendAgentMessage(btn.dataset.prompt));
  });
}

async function sendAgentMessage(message) {
  message = (message || '').trim();
  if (!message) return;
  const transcript = qs('agent-transcript');
  const sendBtn = qs('agent-send-btn');
  qs('agent-input').value = '';

  const userBubble = document.createElement('div');
  userBubble.className = 'card mb-16';
  userBubble.style.background = 'var(--ink-800)';
  userBubble.innerHTML = `<div class="eyebrow">Coordinator</div><div>${escapeHtml(message)}</div>`;
  transcript.appendChild(userBubble);

  const agentBubble = document.createElement('div');
  agentBubble.className = 'card mb-16';
  agentBubble.style.borderColor = 'var(--accent)';
  agentBubble.innerHTML = `<div class="eyebrow">DisasterOps Agent</div><div><span class="spinner"></span> thinking…</div>`;
  transcript.appendChild(agentBubble);
  transcript.scrollIntoView({ behavior: 'smooth', block: 'end' });

  sendBtn.disabled = true;
  try {
    const resp = await fetch(API_BASE + '/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + AuthStore.getToken() },
      body: JSON.stringify({ message, conversation: agentConversation }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      agentBubble.style.borderColor = 'var(--danger)';
      const hint = data.error === 'LLM_NOT_CONFIGURED'
        ? '<div class="small muted" style="margin-top:8px;">Pick an LLM provider in the backend environment (free: <span class="mono">LLM_PROVIDER=ollama</span>, or <span class="mono">GROQ_API_KEY</span> / <span class="mono">GEMINI_API_KEY</span>; paid: <span class="mono">ANTHROPIC_API_KEY</span>) and restart it — see the README.</div>'
        : '';
      agentBubble.innerHTML = `<div class="eyebrow">DisasterOps Agent</div><div style="color:var(--danger);">${escapeHtml(data.message || data.error)}</div>${hint}`;
      return;
    }
    agentConversation = data.conversation;
    agentBubble.innerHTML = renderAgentTrace(data.trace, data.final_message);
  } catch (err) {
    agentBubble.style.borderColor = 'var(--danger)';
    agentBubble.innerHTML = `<div class="eyebrow">DisasterOps Agent</div><div style="color:var(--danger);">${escapeHtml(err.message)}</div>`;
  } finally {
    sendBtn.disabled = false;
  }
}

function renderAgentTrace(trace, finalMessage) {
  const steps = trace.map((step) => {
    if (step.type === 'tool_call') {
      return `<div class="small mono" style="color:var(--info);margin-bottom:2px;">→ ${escapeHtml(step.name)}(${escapeHtml(JSON.stringify(step.input))})</div>`;
    }
    if (step.type === 'tool_result') {
      return `<div class="small mono muted" style="margin-bottom:10px;padding-left:14px;border-left:2px solid var(--line);">${escapeHtml(JSON.stringify(step.result))}</div>`;
    }
    if (step.type === 'assistant_text') {
      return `<div class="small" style="margin-bottom:8px;">${escapeHtml(step.text)}</div>`;
    }
    return '';
  }).join('');

  return `
    <div class="eyebrow">DisasterOps Agent</div>
    <details style="margin-bottom:10px;">
      <summary class="small muted" style="cursor:pointer;">Show tool-call trace (${trace.filter((s) => s.type === 'tool_call').length} calls)</summary>
      <div style="margin-top:8px;">${steps}</div>
    </details>
    <div>${escapeHtml(finalMessage || '(no final message)')}</div>
  `;
}

window.renderCoordinatorAgent = renderCoordinatorAgent;
