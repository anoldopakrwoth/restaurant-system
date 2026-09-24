/* Java House AI assistant. */
(function () {
  const API = window.API_BASE_URL || `${window.location.origin}/api`;
  const originalFetch = window.fetch.bind(window);
  window.fetch = function (url, options = {}) {
    const target = String(url);
    const token = localStorage.getItem('java_house_staff_token');
    const publicRoute = target.includes('/api/health') || target.includes('/api/staff/login');
    if (token && target.includes('/api/') && !publicRoute) {
      options.headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
    }
    return originalFetch(url, options);
  };

  const navButton = document.createElement('button');
  navButton.className = 'nav-btn';
  navButton.dataset.tab = 'ai';
  navButton.innerHTML = '<i class="nav-icon">✦</i><span>AI assistant</span>';
  document.querySelector('.sidebar').insertBefore(navButton, document.querySelector('.sidebar-footer'));

  const panel = document.createElement('div');
  panel.id = 'ai';
  panel.className = 'tab-panel';
  panel.innerHTML = `
    <div class="welcome ai-welcome"><div><div class="eyebrow">Connected operations</div><h1>AI assistant</h1><p class="date">Ask questions about the hotel and restaurant. Answers use your live database.</p></div></div>
    <div class="panel ai-panel">
      <div class="ai-header"><div class="ai-orb">✦</div><div><h2>Java House assistant</h2><p>Live operations support</p></div><span class="ai-live"><i></i> Online</span></div>
      <div class="ai-suggestions"><span>Try asking</span><button type="button" data-ai-suggestion="How many rooms are available today?">Room availability</button><button type="button" data-ai-suggestion="How many bookings do we have today?">Today’s bookings</button><button type="button" data-ai-suggestion="What menu items are available?">Available menu</button></div>
      <div id="ai-messages" class="ai-messages"><div class="ai-message assistant"><div class="ai-avatar">✦</div><div><span class="ai-label">Java House AI</span><div class="ai-bubble">Hello! I can help you check rooms, bookings, tables, menu, orders, and invoices. What would you like to know?</div></div></div></div>
      <form id="ai-form" class="ai-form"><div class="ai-input-wrap"><textarea id="ai-input" aria-label="Your question" placeholder="Ask about today’s operations…" rows="1" required></textarea><span class="ai-hint">Press Enter to send · Shift + Enter for a new line</span></div><button class="ai-send" type="submit" aria-label="Send question">➤</button></form>
    </div>`;
  document.querySelector('.content').appendChild(panel);

  const aiStyle = document.createElement('style');
  aiStyle.textContent = `
    .ai-panel { max-width: 980px; padding: 0; overflow: hidden; background: rgba(255,253,249,.96); }
    .ai-header { display:flex; align-items:center; gap:14px; padding:22px 24px; border-bottom:1px solid var(--line); background:linear-gradient(135deg,#fffdf9,#fff2f4); }
    .ai-orb,.ai-avatar { display:grid; place-items:center; flex:none; color:#fff; background:linear-gradient(135deg,var(--red),#b71439); box-shadow:0 7px 18px #ed294744; }
    .ai-orb { width:48px; height:48px; border-radius:15px; font-size:25px; }
    .ai-header h2 { margin:0; font-size:22px; }
    .ai-header p { color:var(--muted); font-size:13px; margin:2px 0 0; }
    .ai-live { margin-left:auto; color:var(--green); font-size:12px; font-weight:800; display:flex; align-items:center; gap:6px; }
    .ai-live i { width:8px; height:8px; border-radius:50%; background:currentColor; box-shadow:0 0 0 4px #24835e1c; }
    .ai-suggestions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:15px 24px 4px; }
    .ai-suggestions span { color:var(--muted); font-size:12px; margin-right:3px; }
    .ai-suggestions button { border:1px solid #f0cdd2; background:#fff8f9; color:var(--red2); border-radius:999px; padding:8px 12px; cursor:pointer; font-size:12px; }
    .ai-suggestions button:hover { background:#ffe9ed; }
    .ai-messages { min-height:360px; max-height:52vh; overflow-y:auto; padding:20px 24px; scroll-behavior:smooth; }
    .ai-message { display:flex; gap:10px; margin:14px 0; white-space:pre-wrap; line-height:1.55; }
    .ai-message.user { justify-content:flex-end; }
    .ai-message.user > div:last-child { max-width:75%; }
    .ai-message.assistant > div:last-child { max-width:82%; }
    .ai-avatar { width:30px; height:30px; border-radius:10px; font-size:15px; }
    .ai-label { display:block; color:var(--muted); margin:1px 0 5px; font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
    .ai-message.user .ai-label { text-align:right; color:var(--red2); }
    .ai-bubble { padding:12px 15px; border-radius:4px 16px 16px 16px; background:#f3f0eb; color:var(--ink); }
    .ai-message.user .ai-bubble { border-radius:16px 4px 16px 16px; background:var(--red); color:#fff; }
    .ai-form { display:flex; gap:10px; align-items:flex-end; margin:0 20px 20px; padding:10px 10px 10px 15px; border:1px solid #ded8d0; border-radius:16px; background:#fff; box-shadow:0 8px 22px #241f1a0d; }
    .ai-input-wrap { flex:1; }
    .ai-form textarea { display:block; width:100%; min-height:28px; max-height:110px; resize:none; border:0; outline:0; padding:4px 0; background:transparent; font:inherit; }
    .ai-hint { display:block; color:#9a9894; font-size:10px; margin-top:3px; }
    .ai-send { width:42px; height:42px; border:0; border-radius:12px; color:#fff; background:var(--red); cursor:pointer; font-size:20px; }
    .ai-send:hover { background:var(--red2); transform:translateY(-1px); }
    .ai-send:disabled { opacity:.65; cursor:wait; }
    @media(max-width:650px) { .ai-header,.ai-suggestions,.ai-messages { padding-left:16px; padding-right:16px; } .ai-live { display:none; } .ai-message.user > div:last-child,.ai-message.assistant > div:last-child { max-width:88%; } .ai-form { margin-left:12px; margin-right:12px; } .ai-hint { display:none; } }
  `;
  document.head.appendChild(aiStyle);

  const messages = document.getElementById('ai-messages');
  const input = document.getElementById('ai-input');
  function addMessage(role, text) {
    const message = document.createElement('div');
    message.className = `ai-message ${role}`;
    message.innerHTML = role === 'user'
      ? '<div><span class="ai-label">You</span><div class="ai-bubble"></div></div>'
      : '<div class="ai-avatar">✦</div><div><span class="ai-label">Java House AI</span><div class="ai-bubble"></div></div>';
    message.querySelector('.ai-bubble').textContent = text;
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
  }
  document.querySelectorAll('[data-ai-suggestion]').forEach((button) => {
    button.addEventListener('click', () => { input.value = button.dataset.aiSuggestion; input.focus(); });
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); document.getElementById('ai-form').requestSubmit(); }
  });
  document.getElementById('ai-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    addMessage('user', question);
    input.value = '';
    const pending = addMessage('assistant', 'Thinking…');
    const sendButton = document.querySelector('.ai-send');
    sendButton.disabled = true;
    sendButton.textContent = '…';
    try {
      const response = await fetch(`${API}/ai/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: question }) });
      const data = await response.json();
      pending.querySelector('.ai-bubble').textContent = response.ok ? data.answer : (data.error || 'The AI request failed.');
    } catch (error) {
      pending.querySelector('.ai-bubble').textContent = 'The API is not running. Start it with: python app.py';
    }
    sendButton.disabled = false;
    sendButton.textContent = '➤';
  });
})();
