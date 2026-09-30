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
      pending.textContent = data.answer;
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
