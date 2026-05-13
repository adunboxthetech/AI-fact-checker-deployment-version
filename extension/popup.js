const DEFAULT_API_BASE = "https://anindya-das-ai-fact-checker.vercel.app";

const elements = {
  statusText: document.getElementById("statusText"),
  settingsToggle: document.getElementById("settingsToggle"),
  settingsPanel: document.getElementById("settingsPanel"),
  apiBase: document.getElementById("apiBase"),
  saveSettings: document.getElementById("saveSettings"),
  postCard: document.getElementById("postCard"),
  platformBadge: document.getElementById("platformBadge"),
  sourceLink: document.getElementById("sourceLink"),
  postPreview: document.getElementById("postPreview"),
  loadingCard: document.getElementById("loadingCard"),
  loadingText: document.getElementById("loadingText"),
  resultCard: document.getElementById("resultCard"),
  retryBtn: document.getElementById("retryBtn"),
  openAppBtn: document.getElementById("openAppBtn"),
  actionButtons: document.getElementById("actionButtons"),
  themeToggle: document.getElementById("themeToggle"),
  moonIcon: document.getElementById("moonIcon"),
  sunIcon: document.getElementById("sunIcon")
};

let activeTab = null;
let apiBase = DEFAULT_API_BASE;

document.addEventListener("DOMContentLoaded", init);

async function init() {
  if (!hasExtensionApis()) {
    renderHostedFallback();
    return;
  }

  const saved = await chrome.storage.sync.get({ apiBase: DEFAULT_API_BASE, theme: "dark" });
  apiBase = saved.apiBase || DEFAULT_API_BASE;
  elements.apiBase.value = apiBase;

  // Initialize theme
  applyTheme(saved.theme || "dark");

  elements.themeToggle.addEventListener("click", toggleTheme);
  elements.settingsToggle.addEventListener("click", () => {
    elements.settingsPanel.classList.toggle("hidden");
  });
  elements.saveSettings.addEventListener("click", saveSettings);
  elements.retryBtn.addEventListener("click", runCheck);
  elements.openAppBtn.addEventListener("click", openBackendApp);

  runCheck();
}

function hasExtensionApis() {
  return (
    typeof chrome !== "undefined" &&
    chrome.storage &&
    chrome.runtime &&
    chrome.scripting &&
    chrome.tabs
  );
}

function renderHostedFallback() {
  apiBase = DEFAULT_API_BASE;
  elements.apiBase.value = apiBase;
  elements.statusText.textContent = "Extension files are hosted";
  elements.loadingCard.classList.add("hidden");
  elements.postCard.classList.add("hidden");
  elements.resultCard.classList.remove("hidden");
  elements.resultCard.innerHTML = `
    <div class="empty">
      This popup runs when loaded as a Chrome extension. Download or load the extension folder, then click the browser toolbar icon while viewing a social post.
    </div>
  `;
  elements.retryBtn.disabled = true;
  elements.openAppBtn.addEventListener("click", () => {
    window.location.href = DEFAULT_API_BASE;
  });
  elements.settingsToggle.addEventListener("click", () => {
    elements.settingsPanel.classList.toggle("hidden");
  });

  // Theme toggle works even in fallback mode
  const fallbackTheme = localStorage.getItem("ai-fc-ext-theme") || "dark";
  applyTheme(fallbackTheme);
  elements.themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("ai-fc-ext-theme", next); } catch (_) {}
  });
}

// ===== Theme management =====

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  updateThemeIcon(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  if (hasExtensionApis()) {
    chrome.storage.sync.set({ theme: next });
  }
  try { localStorage.setItem("ai-fc-ext-theme", next); } catch (_) {}
}

function updateThemeIcon(theme) {
  if (!elements.moonIcon || !elements.sunIcon) return;
  if (theme === "dark") {
    elements.moonIcon.style.display = "";
    elements.sunIcon.style.display = "none";
  } else {
    elements.moonIcon.style.display = "none";
    elements.sunIcon.style.display = "";
  }
  if (elements.themeToggle) {
    elements.themeToggle.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
    elements.themeToggle.title = `Switch to ${theme === "dark" ? "light" : "dark"} mode`;
  }
}

async function saveSettings() {
  const next = normalizeApiBase(elements.apiBase.value);
  if (!next) {
    showError("Enter a valid backend URL.");
    return;
  }
  apiBase = next;
  elements.apiBase.value = next;
  await chrome.storage.sync.set({ apiBase: next });
  elements.settingsPanel.classList.add("hidden");
  runCheck();
}

function normalizeApiBase(value) {
  try {
    const url = new URL((value || "").trim());
    if (!["http:", "https:"].includes(url.protocol)) return "";
    url.pathname = url.pathname.replace(/\/+$/, "");
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch (_) {
    return "";
  }
}

async function runCheck() {
  elements.actionButtons.classList.add("hidden");
  setLoading("Finding the visible post...");
  clearResults();

  try {
    activeTab = await getActiveTab();
    if (!activeTab || !activeTab.id) {
      throw new Error("No active tab found.");
    }

    const extracted = await extractPost(activeTab.id);
    renderPostPreview(extracted);

    let screenshotDataUrl = null;
    if (shouldCaptureScreenshot(extracted)) {
      setLoading("Reading the visible post image...");
      screenshotDataUrl = await captureVisibleTab();
    }

    setLoading("Fact-checking...");
    const payload = {
      ...extracted,
      screenshot_data_url: screenshotDataUrl,
      page_url: extracted.page_url || activeTab.url || "",
      url: extracted.url || extracted.page_url || activeTab.url || ""
    };
    const result = await factCheck(payload);
    renderResults(result);
    elements.statusText.textContent = "Check complete";
  } catch (error) {
    showError(error.message || "Could not complete the check.");
  } finally {
    elements.loadingCard.classList.add("hidden");
    disperseThoughtBubbles();
  }
}

function getActiveTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      resolve(tabs && tabs[0] ? tabs[0] : null);
    });
  });
}

async function extractPost(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"]
    });
  } catch (_) {
    // The script may already be injected, or the page may reject injection.
  }

  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, { type: "EXTRACT_VISIBLE_POST" }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error("This page cannot be inspected by the extension."));
        return;
      }
      if (!response || !response.ok) {
        reject(new Error((response && response.error) || "No visible post was found."));
        return;
      }
      resolve(response.post);
    });
  });
}

function shouldCaptureScreenshot(post) {
  const text = (post && post.text ? post.text : "").trim();
  return text.length < 80 || Boolean(post && post.has_visible_media && text.length < 420);
}

function captureVisibleTab() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "CAPTURE_VISIBLE_TAB" }, (response) => {
      if (chrome.runtime.lastError || !response || !response.ok) {
        resolve(null);
        return;
      }
      resolve(response.dataUrl);
    });
  });
}

async function factCheck(payload) {
  const response = await fetch(`${apiBase}/api/extension/fact-check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Backend returned HTTP ${response.status}.`);
  }
  return data;
}

function renderPostPreview(post) {
  const preview = (post && post.text ? post.text : "").trim();
  elements.postPreview.textContent = preview || "Image-based or low-text post detected.";
  elements.platformBadge.textContent = post.platform || "Current page";
  const source = post.post_url || post.page_url || activeTab.url || "#";
  elements.sourceLink.href = source;
  elements.postCard.classList.remove("hidden");
  elements.statusText.textContent = "Visible post captured";
}

function renderResults(data) {
  elements.resultCard.innerHTML = "";
  elements.resultCard.classList.remove("hidden");
  elements.actionButtons.classList.remove("hidden");

  const results = Array.isArray(data.fact_check_results) ? data.fact_check_results : [];
  if (!results.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = data.analysis_error || data.image_analysis_error || "No clear factual claim was found.";
    elements.resultCard.appendChild(empty);
    return;
  }

  results.forEach((item, index) => {
    const el = renderClaim(item);
    el.style.setProperty("--i", index);
    elements.resultCard.appendChild(el);
  });
}

function renderClaim(item) {
  const result = item && item.result ? item.result : {};
  const wrapper = document.createElement("article");
  wrapper.className = "claim";

  const claim = document.createElement("div");
  claim.className = "claim-title";
  claim.textContent = item.claim || "Claim";

  const verdict = document.createElement("div");
  verdict.className = `verdict ${verdictClass(result.verdict || "")}`;
  verdict.textContent = `${result.verdict || "UNKNOWN"} - ${result.confidence || "N/A"}%`;

  const explanation = document.createElement("div");
  explanation.className = "explanation";
  explanation.textContent = result.explanation || "No explanation provided.";

  wrapper.append(claim, verdict, explanation);

  const sources = Array.isArray(result.sources) ? result.sources.filter(Boolean) : [];
  if (sources.length) {
    const sourceBox = document.createElement("div");
    sourceBox.className = "sources";
    sourceBox.textContent = "Sources: ";
    sources.slice(0, 4).forEach((url, index) => {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = humanizeUrl(url, index + 1);
      sourceBox.appendChild(link);
      if (index < Math.min(sources.length, 4) - 1) {
        sourceBox.appendChild(document.createTextNode(", "));
      }
    });
    wrapper.appendChild(sourceBox);
  }

  return wrapper;
}

function verdictClass(verdict) {
  const value = String(verdict).toLowerCase();
  if (value.includes("false")) return "false";
  if (value.includes("true") && !value.includes("partial")) return "true";
  return "partial";
}

function humanizeUrl(url, index) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "") || `Source ${index}`;
  } catch (_) {
    return `Source ${index}`;
  }
}

// ===== Thought Bubble System — ported from main app =====

const bubbleMessages = [
  "Analyzing claims...",
  "Cross-referencing sources...",
  "Evaluating evidence...",
  "Verifying credibility...",
  "Checking global databases...",
  "Comparing perspectives..."
];

// Positions in the LOWER half of the popup (55-75% height range)
// so they never overlap the post card at the top.
const bubblePositions = [
  { top: "68%", right: "12%", cls: "pos-top-right" },
  { top: "74%", left: "8%",  cls: "pos-left" },
  { top: "70%", left: "30%", cls: "pos-top-left" },
  { top: "80%", right: "8%", cls: "pos-right" },
  { top: "76%", left: "15%", cls: "pos-bottom-left" },
  { top: "72%", right: "20%", cls: "pos-bottom-right" }
];

let bubbleIndex = 0;
let bubbleInterval = null;
let cloudRunning = false;
const thoughtContainer = document.getElementById("thoughtBubbles");

function startThoughtBubbles() {
  if (!thoughtContainer) return;
  cloudRunning = true;
  bubbleIndex = 0;
  thoughtContainer.innerHTML = "";

  // HIDE the loading card (spinner) — bubbles replace it
  elements.loadingCard.classList.add("hidden");

  // Start cloud loading vortex
  if (typeof mysticalCloud !== "undefined" && mysticalCloud) {
    mysticalCloud.setIntensity(true);
    mysticalCloud.setLoadingState(true);
  }

  _spawnBubble();
  bubbleInterval = setInterval(() => {
    if (!cloudRunning) return;
    _spawnBubble();
  }, 2200);
}

function _spawnBubble() {
  if (!thoughtContainer) return;

  // Fade previous bubbles
  const old = thoughtContainer.querySelectorAll(".thought-bubble:not(.fading)");
  old.forEach(b => {
    b.classList.add("fading");
    setTimeout(() => b.remove(), 400);
  });

  const msg = bubbleMessages[bubbleIndex % bubbleMessages.length];
  const pos = bubblePositions[bubbleIndex % bubblePositions.length];
  bubbleIndex++;

  const bubble = document.createElement("div");
  bubble.className = `thought-bubble ${pos.cls}`;
  bubble.textContent = msg;
  if (pos.top) bubble.style.top = pos.top;
  if (pos.bottom) bubble.style.bottom = pos.bottom;
  if (pos.left) bubble.style.left = pos.left;
  if (pos.right) bubble.style.right = pos.right;
  thoughtContainer.appendChild(bubble);
}

function disperseThoughtBubbles() {
  cloudRunning = false;
  if (bubbleInterval) {
    clearInterval(bubbleInterval);
    bubbleInterval = null;
  }

  // Fade out all bubbles
  if (thoughtContainer) {
    thoughtContainer.querySelectorAll(".thought-bubble").forEach(b => {
      b.classList.add("fading");
      setTimeout(() => b.remove(), 400);
    });
  }

  // Return cloud to ambient
  if (typeof mysticalCloud !== "undefined" && mysticalCloud) {
    mysticalCloud.setIntensity(false);
    mysticalCloud.setLoadingState(false);
  }
}

// ===== Loading / Error helpers =====

function setLoading(text) {
  elements.statusText.textContent = text;

  // "Fact-checking..." phase → hide spinner, show cloud + thought bubbles
  if (text.toLowerCase().includes("fact-check")) {
    elements.loadingCard.classList.add("hidden");
    if (!cloudRunning) {
      startThoughtBubbles();
    }
  } else {
    // Initial extraction phases → show spinner normally
    elements.loadingText.textContent = text;
    elements.loadingCard.classList.remove("hidden");
  }
}

function clearResults() {
  elements.resultCard.innerHTML = "";
  elements.resultCard.classList.add("hidden");
}

function showError(message) {
  elements.statusText.textContent = "Check failed";
  elements.loadingCard.classList.add("hidden");
  disperseThoughtBubbles();
  elements.resultCard.innerHTML = "";
  elements.resultCard.classList.remove("hidden");
  elements.actionButtons.classList.remove("hidden");
  const error = document.createElement("div");
  error.className = "error";
  error.textContent = friendlyError(message);
  elements.resultCard.appendChild(error);
}

function friendlyError(message) {
  const value = String(message || "");
  if (value.toLowerCase().includes("failed to fetch")) {
    return "Could not reach the backend. Start Flask with python app.py or update the backend URL.";
  }
  return value;
}

function openBackendApp() {
  chrome.tabs.create({ url: apiBase });
}
