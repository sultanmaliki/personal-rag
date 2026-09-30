const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const questionEl = document.getElementById("question");
const sendBtn = document.getElementById("send-btn");
const statusEl = document.getElementById("status");

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Minimal, safe markdown rendering for assistant answers: the model tends to
// reply with **bold** and numbered/bulleted lists, which used to show up as
// literal asterisks. HTML-escaping happens FIRST, so nothing in the model's
// output can ever inject a real tag -- only our own hardcoded <strong>/<li>
// wrappers around already-escaped text are ever inserted.
function renderMarkdown(container, text) {
  container.textContent = ""; // clear the "thinking…" placeholder before appending real content
  const html = escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const blocks = html.split(/\n\s*\n/);
  let currentList = null; // { el, type } -- lets consecutive list blocks (the
  // model often puts a blank line between each numbered item) merge into one
  // continuously-numbered <ol>/<ul> instead of each restarting at "1."

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

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    statusEl.textContent = `${data.chunks} chunks indexed`;
  } catch {
    statusEl.textContent = "backend unreachable";
  }
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;

  addMessage("user", question);
  questionEl.value = "";
  sendBtn.disabled = true;
  const pending = addMessage("assistant pending", "thinking…");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    pending.classList.remove("pending");
    if (!res.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((d) => d.msg).join("; ")
        : data.detail || `request failed (${res.status})`;
      pending.textContent = `Error: ${detail}`;
    } else {
      renderMarkdown(pending, data.answer);
      renderSources(pending, data.sources);
    }
  } catch (err) {
    pending.classList.remove("pending");
    pending.textContent = "Error: could not reach the backend.";
  } finally {
    sendBtn.disabled = false;
    questionEl.focus();
  }
});

questionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

checkHealth();
