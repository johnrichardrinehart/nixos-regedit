const state = {
  options: {},
  tree: { name: "NixOS", path: "", children: [], optionKeys: [] },
  expanded: new Set([""]),
  selectedPath: "",
  selectedOptionKey: null,
  evaluatedExpression: null,
  evaluatedExpressionInput: null,
  declarationCopyIndex: 0,
  lastMode: "",
  lastModuleSource: "",
  lastOptionCount: 0,
  lastEvaluationInput: null,
  evaluationInFlight: null,
  filterText: "",
  selectionExplicit: false,
};

const CACHE_DB = "nixos-regedit-cache";
const CACHE_STORE = "evaluations";
const CACHE_VERSION = 1;
const DEFAULT_ARCHIVE_PROXY_URL =
  "https://nixos-regedit-archive-proxy.johnrichardrinehart.workers.dev";
const NETWORK_CONFIG_STORE = "nixos-regedit-standalone-network";

const $ = (id) => document.getElementById(id);

const elements = {
  expression: $("expressionInput"),
  evaluatedRow: $("evaluatedRow"),
  evaluatedExpression: $("evaluatedExpression"),
  moduleSourceRow: $("moduleSourceRow"),
  moduleSource: $("moduleSource"),
  standaloneNetworkRow: $("standaloneNetworkRow"),
  proxyEnabled: $("proxyEnabled"),
  proxyUrl: $("proxyUrl"),
  netrc: $("netrcInput"),
  filter: $("filterInput"),
  allowFetch: $("allowFetch"),
  system: $("systemInput"),
  evaluate: $("evaluateButton"),
  expand: $("expandButton"),
  collapse: $("collapseButton"),
  copyAttributePath: $("copyAttributePathButton"),
  copyFilesystemPath: $("copyFilesystemPathButton"),
  help: $("helpButton"),
  helpOverlay: $("helpOverlay"),
  helpClose: $("helpCloseButton"),
  diagnostics: $("diagnostics"),
  content: $("content"),
  tableRegion: $("tableRegion"),
  tree: $("tree"),
  rows: $("optionRows"),
  details: $("optionDetails"),
  status: $("statusText"),
  count: $("countText"),
};

let pendingUrlOption = null;
let pendingUrlExpanded = null;
let filterTimer = null;
let evaluatorAvailable = false;
let evaluatorLoadSettled = Boolean(window.NixOSRegeditEvaluator);
let standaloneMode = Boolean(window.NixOSRegeditStandalone);

function loadStandaloneNetworkConfig() {
  standaloneMode = Boolean(window.NixOSRegeditStandalone);
  if (!elements.standaloneNetworkRow) return;
  elements.standaloneNetworkRow.hidden = !standaloneMode;
  if (!standaloneMode) return;

  let config = {};
  try {
    config = JSON.parse(window.localStorage.getItem(NETWORK_CONFIG_STORE) || "{}");
  } catch (error) {
    config = {};
  }
  elements.proxyEnabled.checked = config.proxyEnabled !== false;
  elements.proxyUrl.value = config.proxyUrl || DEFAULT_ARCHIVE_PROXY_URL;
  elements.netrc.value = config.netrc || "";
}

function saveStandaloneNetworkConfig() {
  if (!standaloneMode || !elements.standaloneNetworkRow) return;
  const config = {
    proxyEnabled: elements.proxyEnabled.checked,
    proxyUrl: elements.proxyUrl.value.trim(),
    netrc: elements.netrc.value,
  };
  window.localStorage.setItem(NETWORK_CONFIG_STORE, JSON.stringify(config));
}

function standaloneFetchConfig() {
  if (!standaloneMode || !elements.proxyEnabled || !elements.proxyEnabled.checked) return null;
  const proxyUrl = elements.proxyUrl.value.trim();
  if (!proxyUrl) return null;
  return {
    enabled: true,
    proxyUrl,
    netrc: elements.netrc.value,
  };
}

function regeditEvaluator() {
  const evaluator = window.NixOSRegeditEvaluator || null;
  if (
    !evaluator ||
    typeof evaluator.resolve !== "function" ||
    typeof evaluator.evaluate !== "function"
  ) {
    throw new Error(
      "Evaluator is not loaded. NixOS Regedit requires an evaluator with resolve() and evaluate() functions.",
    );
  }
  return evaluator;
}

function refreshEvaluatorAvailability() {
  const evaluator = window.NixOSRegeditEvaluator || null;
  evaluatorAvailable = Boolean(
    evaluator &&
    typeof evaluator.resolve === "function" &&
    typeof evaluator.evaluate === "function",
  );
  elements.evaluate.disabled = !evaluatorAvailable;
  if (evaluatorAvailable) {
    if (!elements.diagnostics.hidden && elements.diagnostics.textContent.includes("No evaluator")) {
      showDiagnostics([]);
    }
  } else if (evaluatorLoadSettled) {
    setStatus("Evaluator unavailable");
    showDiagnostics([
      "No evaluator is available in this build.",
      "Load libeval-wasm or run the Python backend app before evaluating.",
    ]);
  } else {
    setStatus("Loading evaluator");
    showDiagnostics([]);
  }
  return evaluatorAvailable;
}

async function defaultSystem() {
  try {
    const evaluator = regeditEvaluator();
    if (typeof evaluator.currentSystem === "function") {
      const system = await evaluator.currentSystem();
      if (typeof system === "string" && system.trim()) return system.trim();
    }
  } catch (error) {
    return "x86_64-linux";
  }
  return "x86_64-linux";
}

function loadUrlState() {
  const params = new URLSearchParams(window.location.search);
  const expression = params.get("expression");
  const system = params.get("system");
  const filter = params.get("filter");
  const fetchMode = params.get("fetch");
  pendingUrlOption = params.get("option");
  const expanded = params.get("expanded");
  if (expanded) {
    if (expanded === "all") {
      pendingUrlExpanded = "all";
    } else {
      try {
        const parsed = JSON.parse(expanded);
        if (Array.isArray(parsed)) pendingUrlExpanded = parsed.map(String);
      } catch (error) {
        pendingUrlExpanded = expanded.split(",").filter(Boolean);
      }
    }
  }
  if (expression !== null) elements.expression.value = expression;
  if (system !== null) elements.system.value = system;
  if (filter !== null) {
    elements.filter.value = filter;
    state.filterText = filter.trim();
  }
  if (fetchMode !== null) elements.allowFetch.checked = fetchMode === "1" || fetchMode === "true";
}

function updateUrlState() {
  const params = new URLSearchParams();
  const expression = elements.expression.value.trim();
  const system = elements.system.value.trim();
  const filter = state.filterText.trim();
  if (expression) params.set("expression", expression);
  if (system) params.set("system", system);
  if (filter) params.set("filter", filter);
  if (elements.allowFetch.checked) params.set("fetch", "1");
  if (
    state.selectionExplicit &&
    state.selectedOptionKey &&
    state.selectedOptionKey !== defaultOptionKeyForUrl()
  ) {
    params.set("option", state.selectedOptionKey);
  }
  const expanded = Array.from(state.expanded).filter(Boolean).sort();
  if (expanded.length > 0) {
    const allPaths = [];
    collectPaths(state.tree, allPaths);
    const allExpanded = allPaths.filter(Boolean).sort();
    if (allExpanded.length > 0 && expanded.length === allExpanded.length) {
      params.set("expanded", "all");
    } else {
      const expandedJson = JSON.stringify(expanded);
      if (expandedJson.length <= 4000) params.set("expanded", expandedJson);
    }
  }
  const query = params.toString();
  const next = `${window.location.pathname}${query ? `?${query}` : ""}`;
  window.history.replaceState(null, "", next);
}

function openHelp() {
  elements.helpOverlay.hidden = false;
  elements.helpClose.focus();
}

function closeHelp() {
  elements.helpOverlay.hidden = true;
  elements.help.focus();
}

function renderEvaluatedExpression() {
  const expression = elements.expression.value.trim();
  const evaluated = state.evaluatedExpression;
  const show = Boolean(
    evaluated && state.evaluatedExpressionInput === expression && evaluated !== expression,
  );
  elements.evaluatedRow.hidden = !show;
  elements.evaluatedExpression.textContent = show ? evaluated : "";
}

function moduleSourceLabel(mode) {
  if (mode === "flake-nixosModules") return "flake attribute";
  if (mode === "flake-nixosSystem") return "flake.lib.nixosSystem";
  if (mode === "flake-module-list") return "nixos/modules/module-list.nix";
  if (mode === "expression-nixosModules" || mode === "browser-nixosModules") {
    return "input expression";
  }
  return mode || "";
}

function renderModuleSource() {
  const source = state.lastModuleSource || "";
  elements.moduleSourceRow.hidden = !source;
  elements.moduleSource.textContent = source;
}

function expandPath(path) {
  state.expanded.add("");
  const parts = path.split(".").filter(Boolean);
  for (let index = 1; index <= parts.length; index += 1) {
    state.expanded.add(parts.slice(0, index).join("."));
  }
}

function selectOptionKey(optionKey, { expand = true, explicit = false } = {}) {
  const option = state.options[optionKey];
  if (!option) return false;
  state.selectedPath = optionParentPath(optionKey, option);
  state.selectedOptionKey = optionKey;
  state.selectionExplicit = explicit;
  state.declarationCopyIndex = 0;
  if (expand) expandPath(state.selectedPath);
  return true;
}

function setStatus(message) {
  elements.status.textContent = message;
}

function currentEvaluationInput() {
  return {
    expression: elements.expression.value.trim(),
    system: elements.system.value.trim(),
    allowFetch: elements.allowFetch.checked,
  };
}

function sameEvaluationInput(left, right) {
  return Boolean(
    left &&
    right &&
    left.expression === right.expression &&
    left.system === right.system &&
    left.allowFetch === right.allowFetch,
  );
}

function expressionSummary(input) {
  const text = String((input && input.expression) || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "expression";
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

function hasVisibleResults() {
  return Object.keys(state.options).length > 0;
}

function markInputChanged() {
  const input = currentEvaluationInput();
  if (state.evaluationInFlight) {
    if (sameEvaluationInput(input, state.evaluationInFlight)) {
      setStatus(`Still evaluating ${expressionSummary(input)}`);
    } else {
      setStatus("Input changed while evaluating; visible results are not updated yet");
    }
    return;
  }
  if (hasVisibleResults() && !sameEvaluationInput(input, state.lastEvaluationInput)) {
    setStatus("Input changed; visible results are from the previous evaluation");
  }
}

function appendDiagnosticText(parent, text, classes) {
  if (!text) return;
  const span = document.createElement("span");
  span.textContent = text;
  classes.forEach((className) => span.classList.add(className));
  parent.appendChild(span);
}

function diagnosticClasses(state) {
  const classes = [];
  if (state.bold) classes.push("diagnostic-bold");
  if (state.color) classes.push(`diagnostic-${state.color}`);
  return classes;
}

function applySgr(state, codes) {
  if (codes.length === 0) codes = [0];
  codes.forEach((code) => {
    if (code === 0) {
      state.bold = false;
      state.color = "";
    } else if (code === 1) {
      state.bold = true;
    } else if (code === 22) {
      state.bold = false;
    } else if (code === 39) {
      state.color = "";
    } else if (code === 31) {
      state.color = "red";
    } else if (code === 32) {
      state.color = "green";
    } else if (code === 33) {
      state.color = "yellow";
    } else if (code === 34) {
      state.color = "blue";
    } else if (code === 35) {
      state.color = "magenta";
    } else if (code === 36) {
      state.color = "cyan";
    }
  });
}

function renderDiagnosticMessage(message) {
  const fragment = document.createDocumentFragment();
  const state = { bold: false, color: "" };
  const text = String(message || "");
  const escapePattern = /\u001b\][\s\S]*?(?:\u0007|\u001b\\)|\u001b\[[0-?]*[ -/]*[@-~]/g;
  let lastIndex = 0;
  for (const match of text.matchAll(escapePattern)) {
    appendDiagnosticText(fragment, text.slice(lastIndex, match.index), diagnosticClasses(state));
    lastIndex = match.index + match[0].length;
    const sgr = match[0].match(/^\u001b\[([0-9;]*)m$/);
    if (sgr) {
      applySgr(
        state,
        sgr[1]
          .split(";")
          .filter(Boolean)
          .map((part) => Number(part)),
      );
    }
  }
  appendDiagnosticText(fragment, text.slice(lastIndex), diagnosticClasses(state));
  return fragment;
}

function cleanedDiagnosticText(message) {
  return String(message || "")
    .replace(/^evaluating expression:\s*/i, "")
    .replace(/\n{3,}/g, "\n\n")
    .trimEnd();
}

function browserNetworkFailureHint(message) {
  const text = String(message || "");
  if (
    !/browser fetch failed|Failed to execute 'send' on 'XMLHttpRequest'|Failed to load 'https?:\/\//i.test(
      text,
    )
  ) {
    return "";
  }
  return [
    "Browser network failure: the browser could not read the remote URL.",
    "The browser API does not expose enough detail to reliably distinguish CORS, DNS, TLS, offline, or remote-server failures.",
    "If this is a GitHub, GitLab, SourceHut, or tarball archive URL in the standalone page, CORS is the likely cause. Enable the archive proxy, use the Python backend app, or use a CORS-readable pinned archive.",
  ].join("\n");
}

function diagnosticMessageParts(message) {
  const cleaned = cleanedDiagnosticText(message);
  const hint = browserNetworkFailureHint(cleaned);
  return [hint, cleaned].filter(Boolean);
}

function showDiagnostics(messages) {
  const parts = (messages || []).flatMap(diagnosticMessageParts);
  if (parts.length === 0) {
    elements.diagnostics.hidden = true;
    elements.diagnostics.replaceChildren();
    return;
  }
  elements.diagnostics.hidden = false;
  elements.diagnostics.replaceChildren();
  parts.forEach((message, index) => {
    if (index > 0) elements.diagnostics.appendChild(document.createTextNode("\n\n"));
    elements.diagnostics.appendChild(renderDiagnosticMessage(message));
  });
}

function resetResults() {
  state.options = {};
  state.tree = { name: "NixOS", path: "", children: [], optionKeys: [] };
  state.expanded = new Set([""]);
  state.selectedPath = "";
  state.selectedOptionKey = null;
  state.selectionExplicit = false;
  state.lastMode = "";
  state.lastModuleSource = "";
  state.lastOptionCount = 0;
  state.lastEvaluationInput = null;
  elements.content.hidden = true;
  elements.tableRegion.hidden = true;
  elements.rows.replaceChildren();
  elements.tree.replaceChildren();
  elements.details.textContent = "";
  elements.count.textContent = "0 options";
  renderEvaluatedExpression();
  renderModuleSource();
}

function requestFailureMessage(error) {
  const detail = error && error.message ? error.message : String(error);
  return ["Evaluation failed.", detail].filter(Boolean).join("\n\n");
}

function openCacheDb() {
  if (!("indexedDB" in window)) return Promise.resolve(null);
  return new Promise((resolve) => {
    const request = indexedDB.open(CACHE_DB, CACHE_VERSION);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(CACHE_STORE, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
}

async function cacheKeyFor(identity) {
  const source = JSON.stringify(identity);
  if (!window.crypto || !window.crypto.subtle) return source;
  const bytes = new TextEncoder().encode(source);
  const digest = await window.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function cacheIdentityFor(expression, allowFetch, system) {
  const fetchProxy = standaloneFetchConfig();
  const payload = await regeditEvaluator().resolve({
    expression,
    allowFetch,
    system,
    fetchProxy,
  });
  if (!payload.ok) {
    const attempts = (payload.attempts || []).map(
      (attempt) => `${attempt.mode}: ${attempt.stderr || "failed"}`,
    );
    throw new Error([payload.error, ...attempts].filter(Boolean).join("\n\n"));
  }
  return {
    kind: payload.kind,
    identity: payload.identity,
    system: payload.system,
    allowFetch,
    fetchProxy: standaloneMode
      ? {
          enabled: Boolean(fetchProxy),
          proxyUrl: fetchProxy ? fetchProxy.proxyUrl : "",
        }
      : null,
  };
}

async function cacheGet(key) {
  const db = await openCacheDb();
  if (!db) return null;
  return new Promise((resolve) => {
    const request = db.transaction(CACHE_STORE, "readonly").objectStore(CACHE_STORE).get(key);
    request.onsuccess = () => resolve(request.result ? request.result.payload : null);
    request.onerror = () => resolve(null);
  });
}

async function cachePut(key, payload) {
  const db = await openCacheDb();
  if (!db) return;
  const record = { key, savedAt: Date.now(), payload };
  return new Promise((resolve) => {
    const request = db.transaction(CACHE_STORE, "readwrite").objectStore(CACHE_STORE).put(record);
    request.onsuccess = () => resolve();
    request.onerror = () => resolve();
  });
}

function optionSegments(key, option) {
  if (Array.isArray(option.loc) && option.loc.length > 0) {
    return option.loc.map(String);
  }
  return key.split(".").filter(Boolean);
}

function buildTreeFromOptions(options) {
  const root = { name: "NixOS", path: "", children: [], optionKeys: [] };
  const childMaps = new WeakMap();
  const childrenFor = (node) => {
    let map = childMaps.get(node);
    if (!map) {
      map = new Map();
      childMaps.set(node, map);
    }
    return map;
  };
  const ensureChild = (node, name, path) => {
    const children = childrenFor(node);
    if (children.has(name)) return children.get(name);
    const child = { name, path, children: [], optionKeys: [] };
    children.set(name, child);
    node.children.push(child);
    return child;
  };

  Object.entries(options)
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([key, option]) => {
      const segments = optionSegments(key, option);
      let node = root;
      for (let index = 0; index < segments.length - 1; index += 1) {
        const path = segments.slice(0, index + 1).join(".");
        node = ensureChild(node, segments[index], path);
      }
      node.optionKeys.push(key);
    });

  return root;
}

function normalizeFilterText(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function filterParts(value = state.filterText) {
  return value.split(".").map(normalizeFilterText).filter(Boolean);
}

function fuzzyMatchComponent(needle, haystack) {
  if (!needle) return true;
  if (haystack.includes(needle)) return true;
  let position = 0;
  for (const character of haystack) {
    if (character === needle[position]) position += 1;
    if (position === needle.length) return true;
  }
  return false;
}

function optionMatchesFilter(key, option, parts = filterParts()) {
  if (parts.length === 0) return true;
  const segments = optionSegments(key, option).map(normalizeFilterText).filter(Boolean);
  let segmentIndex = 0;
  for (const part of parts) {
    let matched = false;
    while (segmentIndex < segments.length) {
      if (fuzzyMatchComponent(part, segments[segmentIndex])) {
        matched = true;
        segmentIndex += 1;
        break;
      }
      segmentIndex += 1;
    }
    if (!matched) return false;
  }
  return true;
}

function filteredEntries(parts = filterParts()) {
  return Object.entries(state.options)
    .filter(([key, option]) => optionMatchesFilter(key, option, parts))
    .sort(([a], [b]) => a.localeCompare(b));
}

function filteredTreeNode(node, matchingKeys) {
  const children = node.children
    .map((child) => filteredTreeNode(child, matchingKeys))
    .filter(Boolean);
  const optionKeys = node.optionKeys.filter((key) => matchingKeys.has(key));
  if (node.path === "" || children.length > 0 || optionKeys.length > 0) {
    return { ...node, children, optionKeys };
  }
  return null;
}

function visibleTree(parts = filterParts()) {
  if (parts.length === 0) return state.tree;
  const matchingKeys = new Set(filteredEntries(parts).map(([key]) => key));
  return (
    filteredTreeNode(state.tree, matchingKeys) || {
      name: "NixOS",
      path: "",
      children: [],
      optionKeys: [],
    }
  );
}

function ensureVisibleSelection(parts = filterParts()) {
  if (parts.length === 0) return;
  if (
    state.selectedOptionKey &&
    state.options[state.selectedOptionKey] &&
    optionMatchesFilter(state.selectedOptionKey, state.options[state.selectedOptionKey], parts)
  ) {
    return;
  }
  const firstMatch = filteredEntries(parts)[0];
  if (firstMatch) {
    selectOptionKey(firstMatch[0], { expand: false, explicit: false });
    return;
  }
  state.selectedPath = "";
  state.selectedOptionKey = null;
  state.selectionExplicit = false;
}

function defaultOptionKeyForUrl() {
  const parts = filterParts();
  if (parts.length > 0) {
    const firstMatch = filteredEntries(parts)[0];
    return firstMatch ? firstMatch[0] : null;
  }
  const firstNode = state.tree.children[0];
  return firstNode ? firstNode.optionKeys[0] || null : null;
}

function optionParentPath(key, option) {
  const segments = optionSegments(key, option);
  return segments.slice(0, -1).join(".");
}

function optionsForPath(path, parts = filterParts()) {
  return Object.entries(state.options)
    .filter(([key, option]) => optionParentPath(key, option) === path)
    .filter(([key, option]) => optionMatchesFilter(key, option, parts))
    .sort(([a], [b]) => a.localeCompare(b));
}

function formatData(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "object" && value._type === "literalExpression") return value.text || "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function optionLeafName(key, option) {
  const segments = optionSegments(key, option);
  return segments[segments.length - 1] || key;
}

function rowData(option) {
  return formatData(option.default ?? option.example ?? "");
}

function renderTree() {
  const tree = visibleTree();
  elements.tree.replaceChildren(...tree.children.map((child) => renderTreeNode(child)));
}

function renderTreeNode(node) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";

  const row = document.createElement("div");
  row.className = "tree-row";
  if (node.path === state.selectedPath) row.classList.add("selected");
  row.dataset.path = node.path;

  const twisty = document.createElement("span");
  twisty.className = "twisty";
  const filterActive = filterParts().length > 0;
  const expanded = filterActive || state.expanded.has(node.path);
  twisty.textContent = node.children.length === 0 ? "" : expanded ? "-" : "+";
  row.append(twisty);

  const icon = document.createElement("span");
  icon.className = "key-icon";
  row.append(icon);

  const label = document.createElement("span");
  label.textContent = node.name;
  row.append(label);

  row.addEventListener("click", () => {
    state.selectedPath = node.path;
    state.selectedOptionKey = node.optionKeys[0] || null;
    state.selectionExplicit = true;
    state.declarationCopyIndex = 0;
    if (node.children.length > 0) {
      if (state.expanded.has(node.path)) state.expanded.delete(node.path);
      else state.expanded.add(node.path);
    }
    renderAll();
    updateUrlState();
  });

  wrapper.append(row);
  if (node.children.length > 0 && expanded) {
    const children = document.createElement("div");
    children.className = "tree-children";
    node.children.forEach((child) => children.append(renderTreeNode(child)));
    wrapper.append(children);
  }
  return wrapper;
}

function renderRows() {
  const parts = filterParts();
  ensureVisibleSelection(parts);
  const allRows = optionsForPath(state.selectedPath, parts);
  const rows = allRows;

  elements.tableRegion.hidden = allRows.length <= 1;
  elements.rows.replaceChildren();
  rows.forEach(([key, option]) => {
    const tr = document.createElement("tr");
    if (key === state.selectedOptionKey) tr.classList.add("selected");
    tr.addEventListener("click", () => {
      state.selectedOptionKey = key;
      state.selectionExplicit = true;
      state.declarationCopyIndex = 0;
      renderRows();
      renderDetails();
      updateUrlState();
    });

    const name = document.createElement("td");
    name.textContent = optionLeafName(key, option);
    const type = document.createElement("td");
    type.textContent = option.type || "";
    const data = document.createElement("td");
    data.textContent = rowData(option);
    tr.append(name, type, data);
    elements.rows.append(tr);
  });
  const total = Object.keys(state.options).length;
  if (parts.length > 0) {
    elements.count.textContent = `${rows.length} of ${filteredEntries(parts).length} matching options`;
  } else {
    elements.count.textContent = `${rows.length} of ${total} options`;
  }
}

function renderDetails() {
  const key = state.selectedOptionKey;
  const option = key ? state.options[key] : null;

  if (!option) {
    elements.details.textContent = "";
    return;
  }

  const grid = document.createElement("div");
  grid.className = "detail-grid";
  const add = (label, value, pre = false) => {
    const labelNode = document.createElement("div");
    labelNode.className = "detail-label";
    labelNode.textContent = label;
    const valueNode = document.createElement("div");
    if (pre) {
      const code = document.createElement("pre");
      code.textContent = value;
      valueNode.append(code);
    } else {
      valueNode.textContent = value;
    }
    grid.append(labelNode, valueNode);
  };

  add("Path", key);
  add("Type", option.type || "");
  add("Read only", option.readOnly ? "true" : "false");
  add("Default", formatData(option.default), true);
  add("Example", formatData(option.example), true);
  add("Description", formatData(option.description), true);
  add(
    "Declarations",
    Array.isArray(option.declarations) ? option.declarations.join("\n") : "",
    true,
  );
  add("Related packages", formatData(option.relatedPackages), true);

  elements.details.replaceChildren(grid);
}

function renderAll() {
  ensureVisibleSelection();
  renderTree();
  renderRows();
  renderDetails();
}

function renderEvaluation(payload, { cached = false, input = currentEvaluationInput() } = {}) {
  state.options = payload.options || {};
  state.tree = payload.tree || buildTreeFromOptions(state.options);
  state.lastMode = payload.mode || "";
  state.lastModuleSource = payload.moduleSource || moduleSourceLabel(payload.mode);
  state.lastOptionCount = payload.optionCount || Object.keys(state.options).length;
  state.lastEvaluationInput = input;
  if (pendingUrlExpanded === "all") {
    const paths = [];
    collectPaths(state.tree, paths);
    state.expanded = new Set(paths);
  } else {
    state.expanded = new Set(["", ...(pendingUrlExpanded || [])]);
  }
  state.selectedPath = state.tree.children[0] ? state.tree.children[0].path : "";
  state.selectedOptionKey = state.tree.children[0]
    ? state.tree.children[0].optionKeys[0] || null
    : null;
  state.selectionExplicit = false;
  if (pendingUrlOption) {
    selectOptionKey(pendingUrlOption, { expand: true, explicit: true });
    pendingUrlOption = null;
  }
  pendingUrlExpanded = null;
  elements.content.hidden = false;
  renderAll();
  showDiagnostics([]);
  renderEvaluatedExpression();
  renderModuleSource();
  const parts = filterParts();
  if (!sameEvaluationInput(currentEvaluationInput(), input)) {
    setStatus("Evaluation finished; input changed since these results were produced");
  } else if (parts.length > 0) {
    setStatus(`${filteredEntries(parts).length} matching options${cached ? " (cached)" : ""}`);
  } else {
    setStatus(`${payload.mode}: ${payload.optionCount} options${cached ? " (cached)" : ""}`);
  }
  updateUrlState();
}

async function evaluate() {
  if (!refreshEvaluatorAvailability()) return;
  const input = currentEvaluationInput();
  const expression = input.expression;
  const system = input.system;
  const allowFetch = input.allowFetch;
  if (state.evaluationInFlight) {
    if (sameEvaluationInput(input, state.evaluationInFlight)) {
      setStatus(`Already evaluating ${expressionSummary(input)}`);
    } else {
      setStatus("Still evaluating previous input; changed input has not been evaluated");
    }
    return;
  }
  if (!expression) {
    resetResults();
    showDiagnostics(["expression is required"]);
    setStatus("Missing expression");
    return;
  }
  state.evaluationInFlight = input;
  elements.evaluate.disabled = true;
  if (hasVisibleResults() && !sameEvaluationInput(input, state.lastEvaluationInput)) {
    setStatus(
      `Evaluating changed input; previous results still shown: ${expressionSummary(input)}`,
    );
  } else {
    setStatus(`Evaluating ${expressionSummary(input)}`);
  }
  showDiagnostics([]);
  try {
    const cacheIdentity = await cacheIdentityFor(expression, allowFetch, system);
    state.evaluatedExpression =
      cacheIdentity && cacheIdentity.kind === "flake" ? cacheIdentity.identity : null;
    state.evaluatedExpressionInput = expression;
    const cacheKey = cacheIdentity ? await cacheKeyFor(cacheIdentity) : null;
    if (cacheKey) {
      const cached = await cacheGet(cacheKey);
      if (cached) {
        renderEvaluation(cached, { cached: true, input });
        return;
      }
    }

    const payload = await regeditEvaluator().evaluate({
      expression,
      allowFetch,
      system,
      fetchProxy: standaloneFetchConfig(),
    });
    if (!payload.ok) {
      const attempts = (payload.attempts || []).map(
        (attempt) => `${attempt.mode}: ${attempt.stderr || "failed"}`,
      );
      resetResults();
      showDiagnostics([payload.error, ...attempts]);
      setStatus("Evaluation failed");
      return;
    }
    if (cacheKey) await cachePut(cacheKey, payload);
    renderEvaluation(payload, { input });
  } catch (error) {
    resetResults();
    showDiagnostics([requestFailureMessage(error)]);
    setStatus("Evaluation failed");
  } finally {
    state.evaluationInFlight = null;
    elements.evaluate.disabled = false;
  }
}

function collectPaths(node, paths) {
  paths.push(node.path);
  node.children.forEach((child) => collectPaths(child, paths));
}

async function copyText(text, message = "Copied path") {
  if (!text) return;
  await navigator.clipboard.writeText(text);
  setStatus(message);
}

function selectedDeclarationPath() {
  const option = selectedDeclarationOption();
  if (option && Array.isArray(option.declarations) && option.declarations.length > 0) {
    const index = state.declarationCopyIndex % option.declarations.length;
    state.declarationCopyIndex += 1;
    return option.declarations[index];
  }
  return "";
}

function optionUnderSelectedPath(optionKey, option) {
  if (!state.selectedPath) return true;
  const segments = optionSegments(optionKey, option);
  const selected = state.selectedPath.split(".").filter(Boolean);
  return selected.every((segment, index) => segments[index] === segment);
}

function selectedDeclarationOption() {
  const rowOption = state.selectedOptionKey ? state.options[state.selectedOptionKey] : null;
  if (rowOption && Array.isArray(rowOption.declarations) && rowOption.declarations.length > 0) {
    return rowOption;
  }

  const parts = filterParts();
  const entry = Object.entries(state.options)
    .filter(([key, option]) => optionUnderSelectedPath(key, option))
    .filter(([key, option]) => optionMatchesFilter(key, option, parts))
    .filter(([, option]) => Array.isArray(option.declarations) && option.declarations.length > 0)
    .sort(([left], [right]) => left.localeCompare(right))[0];
  return entry ? entry[1] : null;
}

function applyFilter() {
  if (filterTimer) {
    window.clearTimeout(filterTimer);
    filterTimer = null;
  }
  state.filterText = elements.filter.value.trim();
  renderAll();
  const parts = filterParts();
  if (parts.length > 0) {
    setStatus(`${filteredEntries(parts).length} matching options`);
  } else if (state.lastMode) {
    setStatus(`${state.lastMode}: ${state.lastOptionCount} options`);
  } else {
    setStatus("Ready");
  }
  updateUrlState();
}

function scheduleFilter() {
  if (filterTimer) window.clearTimeout(filterTimer);
  filterTimer = window.setTimeout(applyFilter, 500);
  const pending = elements.filter.value.trim();
  if (pending) setStatus("Filter pending");
}

elements.evaluate.addEventListener("click", evaluate);
elements.expression.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    evaluate();
  }
});
elements.expression.addEventListener("input", () => {
  state.selectedOptionKey = null;
  state.evaluatedExpression = null;
  state.evaluatedExpressionInput = null;
  renderEvaluatedExpression();
  markInputChanged();
  updateUrlState();
});
elements.filter.addEventListener("input", scheduleFilter);
elements.filter.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    applyFilter();
  }
});
elements.system.addEventListener("input", () => {
  state.evaluatedExpression = null;
  state.evaluatedExpressionInput = null;
  renderEvaluatedExpression();
  markInputChanged();
  updateUrlState();
});
elements.allowFetch.addEventListener("change", () => {
  markInputChanged();
  updateUrlState();
});
if (elements.proxyEnabled) {
  elements.proxyEnabled.addEventListener("change", saveStandaloneNetworkConfig);
  elements.proxyUrl.addEventListener("input", saveStandaloneNetworkConfig);
  elements.netrc.addEventListener("input", saveStandaloneNetworkConfig);
}
elements.expand.addEventListener("click", () => {
  const paths = [];
  collectPaths(state.tree, paths);
  state.expanded = new Set(paths);
  renderTree();
  updateUrlState();
});
elements.collapse.addEventListener("click", () => {
  state.expanded = new Set([""]);
  renderTree();
  updateUrlState();
});
elements.copyAttributePath.addEventListener("click", () =>
  copyText(state.selectedOptionKey || state.selectedPath),
);
elements.copyFilesystemPath.addEventListener("click", () => {
  const option = selectedDeclarationOption();
  const total = option && Array.isArray(option.declarations) ? option.declarations.length : 0;
  const index = total > 0 ? (state.declarationCopyIndex % total) + 1 : 0;
  copyText(
    selectedDeclarationPath(),
    total > 0 ? `Copied filesystem path ${index} of ${total}` : "No filesystem path",
  );
});
elements.help.addEventListener("click", openHelp);
elements.helpClose.addEventListener("click", closeHelp);
elements.helpOverlay.addEventListener("click", (event) => {
  if (event.target === elements.helpOverlay) closeHelp();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.helpOverlay.hidden) {
    event.preventDefault();
    closeHelp();
  }
});

loadUrlState();
loadStandaloneNetworkConfig();
renderEvaluatedExpression();
renderAll();
refreshEvaluatorAvailability();
window.addEventListener("nixos-regedit-evaluator-ready", () => {
  evaluatorLoadSettled = true;
  if (refreshEvaluatorAvailability() && elements.expression.value.trim()) evaluate();
});
window.addEventListener("nixos-regedit-evaluator-failed", (event) => {
  evaluatorLoadSettled = true;
  refreshEvaluatorAvailability();
  if (event.detail) showDiagnostics([String(event.detail)]);
});
window.setTimeout(() => {
  if (!evaluatorAvailable) {
    evaluatorLoadSettled = true;
    refreshEvaluatorAvailability();
  }
}, 15000);

defaultSystem().then((system) => {
  elements.system.placeholder = system;
  if (evaluatorAvailable && elements.expression.value.trim()) evaluate();
});
