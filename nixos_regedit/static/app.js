const state = {
  options: {},
  tree: { name: "NixOS", path: "", children: [], optionKeys: [] },
  expanded: new Set([""]),
  selectedPath: "",
  selectedOptionKey: null,
};

const $ = (id) => document.getElementById(id);

const elements = {
  expression: $("expressionInput"),
  allowFetch: $("allowFetch"),
  evaluate: $("evaluateButton"),
  expand: $("expandButton"),
  collapse: $("collapseButton"),
  copyPath: $("copyPathButton"),
  copyJson: $("copyJsonButton"),
  address: $("addressInput"),
  diagnostics: $("diagnostics"),
  tree: $("tree"),
  rows: $("optionRows"),
  filter: $("filterInput"),
  details: $("optionDetails"),
  status: $("statusText"),
  count: $("countText"),
};

function setStatus(message) {
  elements.status.textContent = message;
}

function showDiagnostics(messages) {
  if (!messages || messages.length === 0) {
    elements.diagnostics.hidden = true;
    elements.diagnostics.textContent = "";
    return;
  }
  elements.diagnostics.hidden = false;
  elements.diagnostics.textContent = messages.join("\n\n");
}

function optionSegments(key, option) {
  if (Array.isArray(option.loc) && option.loc.length > 0) {
    return option.loc.map(String);
  }
  return key.split(".").filter(Boolean);
}

function optionsForPath(path) {
  const prefix = path ? `${path}.` : "";
  return Object.entries(state.options)
    .filter(([key, option]) => {
      const joined = optionSegments(key, option).join(".");
      return !path || joined === path || joined.startsWith(prefix);
    })
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
  elements.tree.replaceChildren(renderTreeNode(state.tree));
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
  twisty.textContent = node.children.length === 0 ? "" : state.expanded.has(node.path) ? "-" : "+";
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
    if (node.children.length > 0) {
      if (state.expanded.has(node.path)) state.expanded.delete(node.path);
      else state.expanded.add(node.path);
    }
    renderAll();
  });

  wrapper.append(row);
  if (node.children.length > 0 && state.expanded.has(node.path)) {
    const children = document.createElement("div");
    children.className = "tree-children";
    node.children.forEach((child) => children.append(renderTreeNode(child)));
    wrapper.append(children);
  }
  return wrapper;
}

function renderRows() {
  const filter = elements.filter.value.trim().toLowerCase();
  const rows = optionsForPath(state.selectedPath).filter(([key, option]) => {
    if (!filter) return true;
    return `${key} ${option.type || ""} ${rowData(option)}`.toLowerCase().includes(filter);
  });

  elements.rows.replaceChildren();
  rows.forEach(([key, option]) => {
    const tr = document.createElement("tr");
    if (key === state.selectedOptionKey) tr.classList.add("selected");
    tr.addEventListener("click", () => {
      state.selectedOptionKey = key;
      renderRows();
      renderDetails();
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
  elements.count.textContent = `${rows.length} of ${Object.keys(state.options).length} options`;
}

function renderDetails() {
  const key = state.selectedOptionKey;
  const option = key ? state.options[key] : null;
  elements.address.value = `Computer\\NixOS${state.selectedPath ? `\\${state.selectedPath.replaceAll(".", "\\")}` : ""}`;

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
  add("Declarations", Array.isArray(option.declarations) ? option.declarations.join("\n") : "", true);
  add("Related packages", formatData(option.relatedPackages), true);
  add("Raw JSON", JSON.stringify(option, null, 2), true);

  elements.details.replaceChildren(grid);
}

function renderAll() {
  renderTree();
  renderRows();
  renderDetails();
}

async function evaluate() {
  const expression = elements.expression.value.trim();
  if (!expression) {
    showDiagnostics(["expression is required"]);
    setStatus("Missing expression");
    return;
  }
  elements.evaluate.disabled = true;
  setStatus("Evaluating");
  showDiagnostics([]);
  try {
    const response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expression, allowFetch: elements.allowFetch.checked }),
    });
    const payload = await response.json();
    if (!payload.ok) {
      const attempts = (payload.attempts || []).map((attempt) => `${attempt.mode}: ${attempt.stderr || "failed"}`);
      showDiagnostics([payload.error, ...attempts]);
      setStatus("Evaluation failed");
      return;
    }
    state.options = payload.options || {};
    state.tree = payload.tree || { name: "NixOS", path: "", children: [], optionKeys: [] };
    state.expanded = new Set([""]);
    state.selectedPath = "";
    state.selectedOptionKey = Object.keys(state.options).sort()[0] || null;
    renderAll();
    showDiagnostics((payload.diagnostics || []).map((item) => item.message || String(item)));
    setStatus(`${payload.mode}: ${payload.optionCount} options`);
  } catch (error) {
    showDiagnostics([String(error)]);
    setStatus("Request failed");
  } finally {
    elements.evaluate.disabled = false;
  }
}

function collectPaths(node, paths) {
  paths.push(node.path);
  node.children.forEach((child) => collectPaths(child, paths));
}

async function copyText(text) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
  setStatus("Copied");
}

elements.evaluate.addEventListener("click", evaluate);
elements.filter.addEventListener("input", () => {
  renderRows();
  renderDetails();
});
elements.expand.addEventListener("click", () => {
  const paths = [];
  collectPaths(state.tree, paths);
  state.expanded = new Set(paths);
  renderTree();
});
elements.collapse.addEventListener("click", () => {
  state.expanded = new Set([""]);
  renderTree();
});
elements.copyPath.addEventListener("click", () => copyText(state.selectedOptionKey || state.selectedPath));
elements.copyJson.addEventListener("click", () => {
  const option = state.selectedOptionKey ? state.options[state.selectedOptionKey] : null;
  copyText(option ? JSON.stringify(option, null, 2) : "");
});

renderAll();
