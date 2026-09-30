const sidebar = document.getElementById("sidebar");
const collapseBtn = document.getElementById("collapse-btn");
const openSidebarBtn = document.getElementById("open-sidebar-btn");
const newChatBtn = document.getElementById("new-chat-btn");
const conversationListEl = document.getElementById("conversation-list");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const emptyStateEl = document.getElementById("empty-state");
const conversationTitleEl = document.getElementById("conversation-title");
const renameBtn = document.getElementById("rename-btn");
const formEl = document.getElementById("chat-form");
const questionEl = document.getElementById("question");
const sendBtn = document.getElementById("send-btn");
const modalOverlay = document.getElementById("modal-overlay");
const modal = document.getElementById("modal");
const modalTitle = document.getElementById("modal-title");
const modalMessage = document.getElementById("modal-message");
const modalInput = document.getElementById("modal-input");
const modalCancel = document.getElementById("modal-cancel");
const modalConfirm = document.getElementById("modal-confirm");

const LAST_CONVERSATION_KEY = "personal-rag:last-conversation-id";
const SIDEBAR_COLLAPSED_KEY = "personal-rag:sidebar-collapsed";

let currentConversationId = null;
let conversationsCache = [];
let isSending = false;

// ---------- utilities ----------

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Minimal, safe markdown rendering: HTML-escape FIRST, then only ever insert
// our own hardcoded tags around already-escaped text -- nothing from the
// model's output can inject real markup this way.
function renderTextSegment(container, text) {
  const html = escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");
  const blocks = html.split(/\n\s*\n/);
  let currentList = null;

  for (const block of blocks) {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) continue;
    const isNumbered = lines.every((l) => /^\d+\.\s/.test(l));
    const isBulleted = lines.every((l) => /^[-*]\s/.test(l));

    if (isNumbered || isBulleted) {
      const type = isNumbered ? "ol" : "ul";
      if (!currentList || currentList.type !== type) {
        currentList = { el: document.createElement(type), type };
        container.appendChild(currentList.el);
      }
      const stripRe = isNumbered ? /^\d+\.\s/ : /^[-*]\s/;
      for (const line of lines) {
        const li = document.createElement("li");
        li.innerHTML = line.replace(stripRe, "");
        currentList.el.appendChild(li);
      }
    } else {
      currentList = null;
      const p = document.createElement("p");
      p.innerHTML = lines.join("<br>");
      container.appendChild(p);
    }
  }
}

function renderCodeBlock(container, lang, code) {
  const wrap = document.createElement("div");
  wrap.className = "code-block";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "code-copy-btn";
  copyBtn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="1.6"/><path d="M5 15V6a1 1 0 0 1 1-1h9" stroke="currentColor" stroke-width="1.6"/></svg><span>Copy</span>';
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code);
      const label = copyBtn.querySelector("span");
      label.textContent = "Copied";
      setTimeout(() => { label.textContent = "Copy"; }, 1500);
    } catch {
      // Clipboard API unavailable (e.g. no permission) -- button just won't confirm.
    }
  });

  const pre = document.createElement("pre");
  const codeEl = document.createElement("code");
  if (lang) codeEl.className = `language-${lang}`;
  codeEl.textContent = code; // textContent, not innerHTML -- no escaping needed or wanted here
  pre.appendChild(codeEl);

  wrap.appendChild(copyBtn);
  wrap.appendChild(pre);
  container.appendChild(wrap);
}

// Splits out ```fenced``` code blocks (rendered as monospace + a copy
// button, never markdown-processed) before running the rest of the text
// through the paragraph/list/bold/inline-code pipeline above.
function renderMarkdownInto(container, text) {
  container.textContent = "";
  const fenceRe = /```(\w*)\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;
  let hadCodeBlock = false;

  while ((match = fenceRe.exec(text)) !== null) {
    hadCodeBlock = true;
    const before = text.slice(lastIndex, match.index);
    if (before.trim()) renderTextSegment(container, before);
    renderCodeBlock(container, match[1], match[2].replace(/\n$/, ""));
    lastIndex = fenceRe.lastIndex;
  }
  const rest = text.slice(lastIndex);
  if (rest.trim() || !hadCodeBlock) renderTextSegment(container, rest);
}

function formatRelativeTime(iso) {
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

function autoResizeTextarea() {
  questionEl.style.height = "auto";
  questionEl.style.height = Math.min(questionEl.scrollHeight, 200) + "px";
}

// ---------- modal (replaces native prompt()/confirm(), which look out of
// place next to the rest of the UI and aren't even available in every
// embedding context) ----------

let modalResolve = null;
let modalPreviouslyFocused = null;

function closeModal(result) {
  modalOverlay.hidden = true;
  if (modalPreviouslyFocused) {
    modalPreviouslyFocused.focus();
    modalPreviouslyFocused = null;
  }
  if (modalResolve) {
    modalResolve(result);
    modalResolve = null;
  }
}

function openModal({ title, message, input, defaultValue, confirmLabel, danger }) {
  modalTitle.textContent = title;
  modalMessage.hidden = !message;
  modalMessage.textContent = message || "";
  modalInput.hidden = !input;
  modalInput.value = defaultValue || "";
  modalInput.setAttribute("aria-label", title);
  modalConfirm.textContent = confirmLabel || "OK";
  modalConfirm.className = "modal-btn " + (danger ? "danger" : "primary");
  modalPreviouslyFocused = document.activeElement;
  modalOverlay.hidden = false;

  if (input) {
    modalInput.focus();
    modalInput.select();
  } else {
    modalConfirm.focus();
  }

  return new Promise((resolve) => {
    modalResolve = resolve;
  });
}

// Trap Tab focus inside the modal while it's open -- otherwise keyboard
// users can tab straight through it into the sidebar/chat behind it.
modal.addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const focusable = Array.from(modal.querySelectorAll("button, input:not([hidden])")).filter(
    (el) => el.offsetParent !== null
  );
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
});

async function promptModal(title, defaultValue) {
  const result = await openModal({ title, input: true, defaultValue, confirmLabel: "Save" });
  return result === true ? modalInput.value.trim() : null;
}

async function confirmModal(title, message, confirmLabel) {
  return openModal({ title, message, confirmLabel: confirmLabel || "Confirm", danger: true });
}

modalCancel.addEventListener("click", () => closeModal(false));
modalConfirm.addEventListener("click", () => closeModal(true));
modalOverlay.addEventListener("click", (e) => {
  if (e.target === modalOverlay) closeModal(false);
});
modalInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); closeModal(true); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modalOverlay.hidden) closeModal(false);
});

// ---------- sidebar ----------

const MOBILE_BREAKPOINT = "(max-width: 820px)";

function setSidebarCollapsed(collapsed, persist = true) {
  sidebar.classList.toggle("collapsed", collapsed);
  openSidebarBtn.hidden = !collapsed;
  // Only shown as an overlay scrim below the 820px breakpoint (see
  // style.css); harmless to toggle it unconditionally above that width
  // since [hidden] wins there regardless.
  sidebarBackdrop.hidden = collapsed || !window.matchMedia(MOBILE_BREAKPOINT).matches;
  if (persist) localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
}

sidebarBackdrop.addEventListener("click", () => setSidebarCollapsed(true));

function renderSources(container, sources) {
  if (!sources || sources.length === 0) return;
  const box = document.createElement("div");
  box.className = "sources";
  sources.forEach((s, i) => {
    const line = document.createElement("div");
    if (s.ref) {
      const a = document.createElement("a");
      a.href = s.ref;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = `[${i + 1}] ${s.label}`;
      line.appendChild(a);
    } else {
      line.textContent = `[${i + 1}] ${s.label}`;
    }
    box.appendChild(line);
  });
  container.appendChild(box);
}

function buildThinkingBlock(open) {
  const wrap = document.createElement("div");
  wrap.className = "thinking" + (open ? " open" : "");

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "thinking-toggle";
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
    '<span class="thinking-label">Thinking</span>';
  const spinner = document.createElement("div");
  spinner.className = "thinking-spinner";
  toggle.appendChild(spinner);

  const body = document.createElement("div");
  body.className = "thinking-body";

  toggle.addEventListener("click", () => {
    const isOpen = wrap.classList.toggle("open");
    toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });

  wrap.appendChild(toggle);
  wrap.appendChild(body);
  return { wrap, toggle, body, spinner, label: toggle.querySelector(".thinking-label") };
}

async function loadConversations() {
  try {
    const res = await fetch("/api/conversations");
    conversationsCache = await res.json();
    renderConversationList();
  } catch {
    // sidebar just stays empty; the main chat area still works
  }
}

function renderConversationList() {
  conversationListEl.textContent = "";
  if (conversationsCache.length === 0) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "No conversations yet. Ask something to start one.";
    conversationListEl.appendChild(empty);
    return;
  }
  for (const c of conversationsCache) {
    // A plain container, not a button: it holds two independently-focusable
    // controls (select + delete), and a <button> can't nest another
    // <button> -- that's invalid HTML and screen readers handle it poorly.
    const item = document.createElement("div");
    item.className = "conversation-item" + (c.id === currentConversationId ? " active" : "");

    const title = document.createElement("button");
    title.type = "button";
    title.className = "conversation-title";
    title.textContent = c.title;
    title.title = c.title;
    title.setAttribute("aria-current", c.id === currentConversationId ? "true" : "false");
    title.addEventListener("click", () => selectConversation(c.id));

    const del = document.createElement("button");
    del.type = "button";
    del.className = "conversation-delete";
    del.setAttribute("aria-label", `Delete "${c.title}"`);
    del.innerHTML = '<svg viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(c.id);
    });

    item.appendChild(title);
    item.appendChild(del);
    conversationListEl.appendChild(item);
  }
}

async function deleteConversation(id) {
  const confirmed = await confirmModal("Delete conversation?", "This can't be undone.", "Delete");
  if (!confirmed) return;
  await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  conversationsCache = conversationsCache.filter((c) => c.id !== id);
  if (id === currentConversationId) {
    startNewChat();
  }
  renderConversationList();
}

async function selectConversation(id) {
  if (isSending) return;
  currentConversationId = id;
  localStorage.setItem(LAST_CONVERSATION_KEY, id);
  renderConversationList();

  try {
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) throw new Error("not found");
    const data = await res.json();
    conversationTitleEl.textContent = data.title;
    renameBtn.hidden = false;

    messagesEl.textContent = "";
    if (data.messages.length === 0) {
      messagesEl.appendChild(emptyStateEl);
    } else {
      for (const m of data.messages) renderStoredMessage(m);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  } catch {
    startNewChat();
  }
}

function renderStoredMessage(m) {
  if (m.role === "user") {
    const div = document.createElement("div");
    div.className = "msg user";
    div.textContent = m.content;
    messagesEl.appendChild(div);
    return;
  }

  const div = document.createElement("div");
  div.className = "msg assistant";

  if (m.thinking) {
    const { wrap, label } = buildThinkingBlock(false);
    wrap.querySelector(".thinking-spinner").remove();
    wrap.querySelector(".thinking-body").textContent = m.thinking;
    label.textContent = "Thinking";
    div.appendChild(wrap);
  }

  const answerBody = document.createElement("div");
  answerBody.className = "answer-body";
  renderMarkdownInto(answerBody, m.content);
  div.appendChild(answerBody);

  renderSources(div, m.sources);
  messagesEl.appendChild(div);
}

function startNewChat() {
  if (isSending) return; // avoid orphaning an in-flight stream's DOM updates
  currentConversationId = null;
  localStorage.removeItem(LAST_CONVERSATION_KEY);
  conversationTitleEl.textContent = "New chat";
  renameBtn.hidden = true;
  messagesEl.textContent = "";
  messagesEl.appendChild(emptyStateEl);
  renderConversationList();
  questionEl.focus();
}

async function renameCurrentConversation() {
  if (!currentConversationId) return;
  const current = conversationsCache.find((c) => c.id === currentConversationId);
  const next = await promptModal("Rename conversation", current ? current.title : "");
  if (!next) return;
  const res = await fetch(`/api/conversations/${currentConversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: next }),
  });
  if (res.ok) {
    const updated = await res.json();
    conversationTitleEl.textContent = updated.title;
    await loadConversations();
  }
}

// ---------- health ----------

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    statusEl.textContent = `${data.chunks} chunks indexed`;
    statusEl.classList.add("ok");
  } catch {
    statusEl.textContent = "backend unreachable";
    statusEl.classList.add("error");
  }
}

// ---------- sending / streaming ----------

async function sendMessage(question) {
  emptyStateEl.remove();

  const userDiv = document.createElement("div");
  userDiv.className = "msg user";
  userDiv.textContent = question;
  messagesEl.appendChild(userDiv);

  const assistantDiv = document.createElement("div");
  assistantDiv.className = "msg assistant pending";
  const { wrap: thinkingWrap, body: thinkingBody, spinner } = buildThinkingBlock(true);
  const answerBody = document.createElement("div");
  answerBody.className = "answer-body";
  const dots = document.createElement("div");
  dots.className = "loading-dots";
  dots.innerHTML = "<span></span><span></span><span></span>";
  answerBody.appendChild(dots);
  assistantDiv.appendChild(thinkingWrap);
  assistantDiv.appendChild(answerBody);
  messagesEl.appendChild(assistantDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  let thinkingText = "";
  let answerText = "";
  let sawThinking = false;
  let sawContent = false;

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, conversation_id: currentConversationId }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail || `request failed (${res.status})`;
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sepIndex;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        if (!rawEvent.startsWith("data: ")) continue;
        const event = JSON.parse(rawEvent.slice(6));

        if (event.type === "conversation") {
          const isNewConversation = currentConversationId !== event.conversation_id;
          currentConversationId = event.conversation_id;
          localStorage.setItem(LAST_CONVERSATION_KEY, currentConversationId);
          if (isNewConversation) await loadConversations();
        } else if (event.type === "thinking") {
          if (!sawThinking) {
            sawThinking = true;
            dots.remove();
          }
          thinkingText += event.delta;
          thinkingBody.textContent = thinkingText;
          thinkingBody.scrollTop = thinkingBody.scrollHeight;
        } else if (event.type === "content") {
          if (!sawContent) {
            sawContent = true;
            dots.remove();
            thinkingWrap.classList.remove("open");
            spinner.remove();
          }
          answerText += event.delta;
          renderMarkdownInto(answerBody, answerText);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        } else if (event.type === "done") {
          assistantDiv.classList.remove("pending");
          spinner.remove();
          if (!thinkingText) thinkingWrap.remove();
          renderSources(assistantDiv, event.sources);
          await loadConversations();
        }
      }
    }
  } catch (err) {
    assistantDiv.classList.remove("pending");
    assistantDiv.classList.add("error");
    spinner.remove();
    thinkingWrap.remove();
    dots.remove();
    answerBody.textContent = `Error: ${err.message || "could not reach the backend."}`;
  }
}

// ---------- events ----------

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (isSending) return;
  const question = questionEl.value.trim();
  if (!question) return;

  questionEl.value = "";
  autoResizeTextarea();
  isSending = true;
  sendBtn.disabled = true;

  await sendMessage(question);

  isSending = false;
  sendBtn.disabled = false;
  questionEl.focus();
});

questionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

questionEl.addEventListener("input", autoResizeTextarea);

newChatBtn.addEventListener("click", startNewChat);
renameBtn.addEventListener("click", renameCurrentConversation);
collapseBtn.addEventListener("click", () => setSidebarCollapsed(true));
openSidebarBtn.addEventListener("click", () => setSidebarCollapsed(false));

// ---------- init ----------

(async function init() {
  const storedCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
  if (storedCollapsed !== null) {
    setSidebarCollapsed(storedCollapsed === "1", false);
  } else if (window.matchMedia(MOBILE_BREAKPOINT).matches) {
    // First visit with no saved preference: on a narrow viewport the
    // sidebar is a full-width drawer, so default it closed rather than
    // covering the chat with no indication there's content behind it.
    setSidebarCollapsed(true, false);
  }
  checkHealth();
  await loadConversations();

  const lastId = localStorage.getItem(LAST_CONVERSATION_KEY);
  if (lastId && conversationsCache.some((c) => c.id === lastId)) {
    await selectConversation(lastId);
  } else {
    startNewChat();
  }
})();
