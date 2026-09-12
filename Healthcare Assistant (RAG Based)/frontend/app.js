// Point this at wherever the FastAPI backend is running.
const API_BASE = window.HEALTHCARE_API_BASE || "http://localhost:8000";

const chatWindow = document.getElementById("chatWindow");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const apiKeyInput = document.getElementById("apiKeyInput");
const apiStatus = document.getElementById("apiStatus");
const tipText = document.getElementById("tipText");
const messageTemplate = document.getElementById("messageTemplate");
const roleSelect = document.getElementById("roleSelect");

let apiKey = localStorage.getItem("healthcare_api_key") || "";
apiKeyInput.value = apiKey;
updateApiStatusUI();

let userRole = localStorage.getItem("healthcare_role") || "front_desk";
roleSelect.value = userRole;
roleSelect.addEventListener("change", () => {
  userRole = roleSelect.value;
  localStorage.setItem("healthcare_role", userRole);
});

apiKeyInput.addEventListener("input", () => {
  apiKey = apiKeyInput.value.trim();
  localStorage.setItem("healthcare_api_key", apiKey);
  updateApiStatusUI();
  refreshHealth();
});

function updateApiStatusUI() {
  if (apiKey) {
    apiStatus.className = "api-status connected";
    apiStatus.innerHTML = "<span class='api-dot'></span> Connected";
  } else {
    apiStatus.className = "api-status not-connected";
    apiStatus.innerHTML = "<span class='api-dot'></span> Not connected";
  }
}

async function refreshHealth() {
  try {
    const url = new URL(API_BASE + "/api/health");
    if (apiKey) url.searchParams.set("api_key", apiKey);
    const res = await fetch(url);
    const data = await res.json();
    if (data.groq_connected) {
      apiStatus.className = "api-status connected";
      apiStatus.innerHTML = "<span class='api-dot'></span> Connected";
    } else if (apiKey) {
      apiStatus.className = "api-status not-connected";
      apiStatus.innerHTML = "<span class='api-dot'></span> Key not working";
    }
  } catch (err) {
    // Backend not reachable yet - keep whatever the UI already shows.
    console.warn("Health check failed", err);
  }
}

async function refreshTip() {
  try {
    const res = await fetch(API_BASE + "/api/tips");
    const data = await res.json();
    tipText.textContent = data.tip;
  } catch (err) {
    console.warn("Tip fetch failed", err);
  }
}

refreshHealth();
refreshTip();
setInterval(refreshTip, 25000);

function addMessage({ role, content, agent, elapsed, recoveryTips, sql, rows, sources, confidence, routingMethod, safetyFlags, escalated, accessRole, warnings }) {
  const node = messageTemplate.content.cloneNode(true);
  const wrapper = node.querySelector(".chat-message");
  wrapper.classList.add(role);

  node.querySelector(".chat-avatar").textContent = role === "user" ? "\u{1F464}" : "\u{1F3E5}";
  node.querySelector(".chat-content").textContent = content;

  const banner = node.querySelector(".escalation-banner");
  if (escalated) {
    banner.style.display = "block";
    banner.textContent = "\u{1F6A8} Possible medical emergency detected \u2014 see guidance above.";
  }

  const flagsEl = node.querySelector(".safety-flags");
  const shownFlags = (safetyFlags || []).filter((f) => f !== "emergency_escalation");
  if (shownFlags.length || (warnings && warnings.length)) {
    flagsEl.style.display = "block";
    const parts = [];
    if (shownFlags.length) parts.push("Safety checks applied: " + shownFlags.join(", "));
    if (warnings && warnings.length) parts.push(warnings.join(" "));
    flagsEl.textContent = parts.join(" \u00B7 ");
  }

  const recoveryCard = node.querySelector(".recovery-card");
  if (recoveryTips && recoveryTips.length) {
    const icons = ["\u{1F6CF}\uFE0F", "\u{1F964}", "\u{1F957}", "\u{1F48A}"];
    recoveryCard.style.display = "block";
    recoveryCard.innerHTML =
      "<div class='recovery-title'>\u{1F33F} Tips that may support faster recovery</div><div class='recovery-grid'>" +
      recoveryTips
        .map(
          (tip, i) =>
            `<div class="recovery-item"><div class="recovery-item-icon">${icons[i % icons.length]}</div><div>${escapeHtml(tip)}</div></div>`
        )
        .join("") +
      "</div>";
  }

  const details = node.querySelector(".extra-details");
  const summary = node.querySelector("summary");
  const extraBody = node.querySelector(".extra-body");

  if (sql) {
    details.style.display = "block";
    summary.textContent = "View generated SQL" + (rows && rows.length ? ` \u00B7 ${rows.length} row(s)` : "");
    extraBody.innerHTML = `<pre>${escapeHtml(sql)}</pre>` + (rows && rows.length ? renderTable(rows) : "<div style='color:#8faa9d'>No matching rows.</div>");
  } else if (sources) {
    details.style.display = "block";
    summary.textContent = `View citations & evidence (${sources.length})`;
    extraBody.innerHTML = sources
      .map(
        (s) =>
          `<div class="extra-source-block">` +
          `<span class="extra-source-title">[${s.citation}] ${escapeHtml(s.title)} \u2013 ${escapeHtml(s.section || "")}</span>` +
          `<span class="extra-source-score">similarity ${s.score} \u00B7 lines ${escapeHtml(s.line_range || "")} \u00B7 ${escapeHtml(s.source)}</span>` +
          `<div>${escapeHtml(s.text)}</div></div>`
      )
      .join("");
  }

  if (role === "assistant") {
    const roleTag = accessRole ? ` \u00B7 role: ${accessRole}` : "";
    node.querySelector(".chat-source").textContent =
      (agent === "Patient Records" ? "\u{1F5C4}\uFE0F " : agent === "Hospital Policies" ? "\u{1F4DA} " : agent === "Access Denied" ? "\u{1F512} " : "\u{1F9E0} ") +
      "Source: " +
      agent +
      (sources ? ` \u00B7 ${sources.length} sources` : "") +
      roleTag;
    if (confidence != null) {
      const pct = Math.round(confidence * 100);
      const level = confidence >= 0.75 ? "high" : confidence >= 0.5 ? "medium" : "low";
      const confEl = node.querySelector(".chat-confidence");
      confEl.textContent = `confidence: ${pct}% (${routingMethod || "n/a"})`;
      confEl.classList.add("confidence-" + level);
    }
    node.querySelector(".chat-time").textContent = elapsed != null ? `${elapsed.toFixed(2)}s` : "";
  } else {
    node.querySelector(".chat-meta").style.display = "none";
  }

  chatWindow.appendChild(node);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function renderTable(rows) {
  const cols = Object.keys(rows[0]);
  const head = "<tr>" + cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("") + "</tr>";
  const body = rows
    .map((r) => "<tr>" + cols.map((c) => `<td>${escapeHtml(String(r[c] ?? ""))}</td>`).join("") + "</tr>")
    .join("");
  return `<table>${head}${body}</table>`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function addTypingIndicator() {
  const node = messageTemplate.content.cloneNode(true);
  const wrapper = node.querySelector(".chat-message");
  wrapper.classList.add("assistant", "typing-placeholder");
  node.querySelector(".chat-avatar").textContent = "\u{1F3E5}";
  node.querySelector(".chat-content").innerHTML = "<span class='typing-dots'><span></span><span></span><span></span></span>";
  node.querySelector(".chat-meta").style.display = "none";
  chatWindow.appendChild(node);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return chatWindow.lastElementChild;
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = chatInput.value.trim();
  if (!query) return;

  addMessage({ role: "user", content: query });
  chatInput.value = "";
  sendBtn.disabled = true;

  const placeholder = addTypingIndicator();

  try {
    const res = await fetch(API_BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, api_key: apiKey || null, role: userRole }),
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    placeholder.remove();
    addMessage({
      role: "assistant",
      content: data.content,
      agent: data.agent,
      elapsed: data.elapsed,
      recoveryTips: data.recovery_tips,
      sql: data.sql,
      rows: data.rows,
      sources: data.sources,
      confidence: data.confidence,
      routingMethod: data.routing_method,
      safetyFlags: data.safety_flags,
      escalated: data.escalated,
      accessRole: data.access_role,
      warnings: data.warnings,
    });
  } catch (err) {
    placeholder.remove();
    addMessage({
      role: "assistant",
      content: "Sorry, I couldn't reach the Healthcare Assistant backend. Make sure the API server is running at " + API_BASE + ".",
      agent: "Error",
      elapsed: 0,
    });
    console.error(err);
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
});
