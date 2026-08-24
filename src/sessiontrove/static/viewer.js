"use strict";

/* All transcript content is rendered with textContent, never innerHTML. */

const state = {
  sessions: [],
  filter: "",
  agentFilter: null,
  session: null,
  activeLeaf: null,
  expanded: false,
};

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

function fmtDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return isNaN(date) ? String(value) : date.toLocaleString();
}

function fmtAge(value) {
  const date = new Date(value);
  if (isNaN(date)) return "";
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
  const steps = [
    [60, "now"],
    [3600, (s) => `${Math.floor(s / 60)}m`],
    [86400, (s) => `${Math.floor(s / 3600)}h`],
    [604800, (s) => `${Math.floor(s / 86400)}d`],
    [2629800, (s) => `${Math.floor(s / 604800)}w`],
    [31557600, (s) => `${Math.floor(s / 2629800)}mo`],
    [Infinity, (s) => `${Math.floor(s / 31557600)}y`],
  ];
  for (const [limit, label] of steps) {
    if (seconds < limit) return typeof label === "string" ? label : label(seconds);
  }
  return "";
}

/* Session list */

function sessionTitle(summary) {
  if (summary.title) return summary.title;
  const cwd = summary.cwd || summary.name || summary.id;
  return cwd.split("/").filter(Boolean).pop() || cwd;
}

function renderFilters() {
  const box = $("filters");
  const agents = [...new Set(state.sessions.map((s) => s.agent))].sort();
  box.replaceChildren();
  box.hidden = agents.length < 2;
  if (box.hidden) return;
  for (const agent of agents) {
    const count = state.sessions.filter((s) => s.agent === agent).length;
    const chip = el("button", "filter-chip", `${agent} ${count}`);
    chip.dataset.agent = agent;
    chip.title = "filter by agent; click again to clear";
    if (state.agentFilter === agent) chip.classList.add("active");
    chip.addEventListener("click", () => {
      state.agentFilter = state.agentFilter === agent ? null : agent;
      renderFilters();
      renderSessionList();
    });
    box.append(chip);
  }
}

function renderSessionList() {
  const list = $("session-list");
  list.replaceChildren();
  const needle = state.filter.trim().toLowerCase();
  for (const summary of state.sessions) {
    if (state.agentFilter && summary.agent !== state.agentFilter) continue;
    const haystack = [
      summary.title,
      summary.cwd,
      summary.preview,
      summary.machine,
      summary.name,
      summary.agent,
    ]
      .join(" ")
      .toLowerCase();
    if (needle && !haystack.includes(needle)) continue;
    const item = el("li", "session-item");
    if (state.session && state.session.id === summary.id) {
      item.classList.add("active");
    }
    const line = el("div", "session-line");
    line.append(el("span", "session-title", sessionTitle(summary)));
    const tag = el("span", "session-agent", summary.agent);
    tag.dataset.agent = summary.agent;
    line.append(tag);
    const age = el("span", "session-age", fmtAge(summary.started));
    age.title = fmtDate(summary.started);
    line.append(age);
    item.append(line);
    if (summary.preview) {
      item.append(el("div", "session-preview", summary.preview));
    }
    item.addEventListener("click", () => openSession(summary.id));
    list.append(item);
  }
  if (!list.children.length) {
    list.append(el("li", "session-empty", "No sessions."));
  }
}

/* Session loading and branch tree */

async function openSession(id) {
  let session;
  try {
    session = await fetchJSON(`/api/session?id=${encodeURIComponent(id)}`);
  } catch (error) {
    $("placeholder").hidden = false;
    $("placeholder").textContent = `Failed to load session: ${error.message}`;
    $("session").hidden = true;
    return;
  }
  state.session = session;
  history.replaceState(null, "", "#" + encodeURIComponent(id));
  indexRecords(session);
  state.activeLeaf = session.records.length
    ? session.records[session.records.length - 1].id
    : null;
  $("placeholder").hidden = true;
  $("session").hidden = false;
  renderSessionList();
  renderMeta(session);
  renderBranches(session);
  renderConversation(session);
}

function indexRecords(session) {
  session.byId = new Map();
  session.order = new Map();
  session.children = new Map();
  session.records.forEach((record, index) => {
    session.byId.set(record.id, record);
    session.order.set(record.id, index);
  });
  for (const record of session.records) {
    record.parent = session.byId.has(record.parentId) ? record.parentId : null;
    if (!session.children.has(record.parent)) {
      session.children.set(record.parent, []);
    }
    session.children.get(record.parent).push(record.id);
  }
}

function pathTo(session, leafId) {
  const path = [];
  let id = leafId;
  while (id !== null && id !== undefined) {
    const record = session.byId.get(id);
    if (!record || path.length > session.records.length) break;
    path.push(record);
    id = record.parent;
  }
  return path.reverse();
}

/* Follow the child written latest in the file, Pi's notion of "current". */
function tipBelow(session, id) {
  let current = id;
  for (;;) {
    const kids = session.children.get(current) || [];
    if (!kids.length) return current;
    current = kids.reduce((a, b) =>
      session.order.get(a) >= session.order.get(b) ? a : b
    );
  }
}

function segmentsFrom(session, startIds) {
  return startIds.map((startId) => {
    const records = [];
    let id = startId;
    for (;;) {
      records.push(session.byId.get(id));
      const kids = session.children.get(id) || [];
      if (kids.length !== 1) {
        return { records, children: segmentsFrom(session, kids) };
      }
      id = kids[0];
    }
  });
}

function firstText(record) {
  for (const part of record.parts || []) {
    if (part.type === "text" && part.text) {
      return part.text.replace(/\s+/g, " ").slice(0, 60);
    }
  }
  return "";
}

function segmentLabel(segment) {
  for (const record of segment.records) {
    if (record.kind === "user" && firstText(record)) {
      return `you: ${firstText(record)}`;
    }
  }
  for (const record of segment.records) {
    if (firstText(record)) return firstText(record);
  }
  const first = segment.records[0];
  if (first.kind === "custom") return `custom: ${first.customType || "?"}`;
  return first.kind || "records";
}

function renderBranches(session) {
  const panel = $("branches");
  const body = $("branches-body");
  body.replaceChildren();
  const leaves = session.records.filter(
    (record) => !(session.children.get(record.id) || []).length
  );
  panel.hidden = leaves.length < 2;
  if (panel.hidden) return;
  $("branches-summary").textContent = `branches (${leaves.length})`;
  body.append(
    renderSegments(session, segmentsFrom(session, session.children.get(null) || []))
  );
}

function renderSegments(session, segments) {
  const list = el("ul", "segments");
  const active = new Set(pathTo(session, state.activeLeaf).map((r) => r.id));
  for (const segment of segments) {
    const item = el("li");
    const button = el("button", "segment");
    const onPath = segment.records.some((record) => active.has(record.id));
    if (onPath) button.classList.add("active");
    button.append(
      el("span", "segment-mark", onPath ? "●" : ""),
      el("span", "segment-count", segment.records.length),
      el("span", "segment-label", segmentLabel(segment))
    );
    const tip = segment.records[segment.records.length - 1].id;
    button.addEventListener("click", () => {
      state.activeLeaf = tipBelow(session, tip);
      renderBranches(session);
      renderConversation(session);
    });
    item.append(button);
    if (segment.children.length) {
      item.append(renderSegments(session, segment.children));
    }
    list.append(item);
  }
  return list;
}

/* Metadata */

function renderMeta(session) {
  const meta = $("meta");
  meta.replaceChildren();
  const cwd = session.meta.cwd || session.id;
  const title = session.meta.title || cwd.split("/").filter(Boolean).pop() || cwd;
  meta.append(el("h2", "", title));
  meta.append(el("div", "meta-path", cwd));
  const facts = $("facts");
  facts.replaceChildren();
  const add = (label, value, title) => {
    if (value === undefined || value === null || value === "") return;
    const fact = el("span", "fact");
    if (title) fact.title = title;
    fact.append(el("span", "fact-label", label), el("span", "", value));
    facts.append(fact);
  };
  const models = new Set();
  let cost = 0;
  let users = 0;
  for (const record of session.records) {
    if (record.kind === "user") users += 1;
    if (record.kind !== "assistant") continue;
    if (record.model) models.add(record.model);
    const total = record.usage && record.usage.cost && record.usage.cost.total;
    if (typeof total === "number") cost += total;
  }
  add("started", fmtDate(session.meta.started));
  add("model", [...models].join(", "));
  add("user messages", users);
  add("records", session.records.length);
  if (cost) add("cost", "$" + cost.toFixed(2));
  const summary = state.sessions.find((s) => s.id === session.id);
  if (summary && summary.machine) add("machine", summary.machine);
  add("session", session.meta.session_id, session.id);
}

/* Conversation */

function renderConversation(session) {
  const container = $("conversation");
  container.replaceChildren();
  if (state.expanded) setExpanded(false);
  let pending = [];
  let sawUser = false;
  const flush = () => {
    if (!pending.length) return;
    if (sawUser) {
      renderTurn(container, pending);
    } else {
      for (const record of pending) container.append(renderRecord(record));
    }
    pending = [];
  };
  for (const record of pathTo(session, state.activeLeaf)) {
    if (record.kind === "user") {
      flush();
      sawUser = true;
      container.append(renderRecord(record));
    } else {
      pending.push(record);
    }
  }
  flush();
  if (!container.children.length) {
    container.append(el("p", "session-empty", "No records."));
  }
}

/* One turn: everything the agent did stays collapsed, the final answer
   gets its own card. */
function renderTurn(container, records) {
  let final = null;
  for (const record of records) {
    const hasText = (record.parts || []).some(
      (part) => part.type === "text" && part.text
    );
    if (record.kind === "assistant" && hasText) final = record;
  }
  const activity = [];
  for (const record of records) {
    if (record === final) {
      const rest = (record.parts || []).filter((part) => part.type !== "text");
      if (rest.length) activity.push({ ...record, parts: rest });
    } else {
      activity.push(record);
    }
  }
  if (activity.length) container.append(renderActivity(activity));
  if (final) {
    const answer = {
      ...final,
      parts: (final.parts || []).filter((part) => part.type === "text"),
    };
    container.append(renderMessage(answer, "agent", final.model || "agent"));
  }
}

function renderActivity(records) {
  let calls = 0;
  let reasoning = 0;
  for (const record of records) {
    if (record.kind !== "assistant") continue;
    for (const part of record.parts || []) {
      if (part.type === "tool_call") calls += 1;
      if (part.type === "thinking") reasoning += 1;
    }
  }
  const bits = [];
  if (calls) bits.push(`${calls} tool call${calls > 1 ? "s" : ""}`);
  if (reasoning) bits.push(`${reasoning} reasoning`);
  if (!bits.length) bits.push(`${records.length} record${records.length > 1 ? "s" : ""}`);
  const duration = spanDuration(records);
  if (duration) bits.push(duration);
  const body = el("div", "activity-body");
  for (const record of records) body.append(renderRecord(record));
  const details = el("details", "collapsible activity");
  details.append(el("summary", "", bits.join(" · ")));
  details.append(body);
  return details;
}

function spanDuration(records) {
  const times = records
    .map((record) => new Date(record.timestamp).getTime())
    .filter((time) => !isNaN(time));
  if (times.length < 2) return "";
  const seconds = Math.round((Math.max(...times) - Math.min(...times)) / 1000);
  if (seconds < 1) return "";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function renderRecord(record) {
  switch (record.kind) {
    case "user":
      return renderMessage(record, "user", "you");
    case "assistant":
      return renderMessage(record, "assistant", record.model || "assistant");
    case "tool_result":
      return renderToolResult(record);
    case "model_change":
      return el(
        "div",
        "chip-row",
        `model: ${record.model || "?"} (${record.provider || "?"})`
      );
    case "thinking_level":
      return el("div", "chip-row", `thinking: ${record.level || "?"}`);
    case "compaction":
      return renderCompaction(record);
    case "custom":
      return renderRaw(record, `custom: ${record.customType || "?"}`, record.raw);
    default:
      return renderRaw(record, "unknown record", record.raw);
  }
}

function renderMessage(record, cls, label) {
  const card = el("article", `record ${cls}`);
  const head = el("header", "record-head");
  head.append(el("span", "role", label));
  if (record.timestamp) {
    const date = new Date(record.timestamp);
    const time = el(
      "time",
      "",
      isNaN(date)
        ? ""
        : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    );
    time.title = fmtDate(record.timestamp);
    head.append(time);
  }
  card.append(head);
  appendParts(card, record.parts || [], cls !== "user");
  return card;
}

function renderToolResult(record) {
  const card = el("article", "record tool-result" + (record.isError ? " error" : ""));
  const body = el("div", "tool-body");
  appendParts(body, record.parts || [], false);
  let lines = 0;
  let images = 0;
  for (const part of record.parts || []) {
    if (part.type === "text" && part.text) lines += part.text.split("\n").length;
    if (part.type === "image") images += 1;
  }
  const stats = [
    lines ? `${lines} lines` : "",
    images ? `${images} image${images > 1 ? "s" : ""}` : "",
  ]
    .filter(Boolean)
    .join(", ");
  const label =
    `${record.toolName || "?"} ${record.isError ? "failed" : "output"}` +
    (stats ? ` · ${stats}` : "");
  card.append(collapsible(label, body, "output"));
  return card;
}

function renderCompaction(record) {
  const card = el("article", "record system");
  const label =
    "compaction" +
    (record.tokensBefore ? ` (${record.tokensBefore} tokens before)` : "");
  card.append(collapsible(label, renderMarkdown(record.summary)));
  return card;
}

function renderRaw(record, label, raw) {
  const card = el("article", "record system");
  card.append(collapsible(label, rawPre(raw)));
  return card;
}

function toolCallLabel(part) {
  let args = part.arguments;
  if (typeof args === "string") {
    try {
      args = JSON.parse(args);
    } catch {
      args = null;
    }
  }
  if (args && typeof args === "object") {
    const command = String(args.command || args.cmd || "").split("\n")[0];
    if (command) return `$ ${command.slice(0, 120)}`;
    const detail = String(
      args.path || args.file_path || args.pattern || ""
    ).split("\n")[0];
    if (detail) return `${part.name || "tool"} ${detail.slice(0, 120)}`;
  }
  return part.name || "tool";
}

function appendParts(target, parts, markdown) {
  for (const part of parts) {
    if (part.type === "text") {
      target.append(
        markdown ? renderMarkdown(part.text) : el("div", "text", part.text || "")
      );
    } else if (part.type === "thinking") {
      target.append(
        collapsible("reasoning", renderMarkdown(part.text), "thinking")
      );
    } else if (part.type === "tool_call") {
      target.append(
        collapsible(toolCallLabel(part), renderArguments(part.arguments), "call")
      );
    } else if (part.type === "image") {
      target.append(renderImage(part));
    } else {
      target.append(collapsible("unknown content", rawPre(part.raw ?? part)));
    }
  }
}

function collapsible(label, body, cls) {
  const details = el("details", "collapsible" + (cls ? " " + cls : ""));
  details.append(el("summary", "", label));
  details.append(body);
  return details;
}

function toggleExpand() {
  setExpanded(!state.expanded);
}

function setExpanded(expanded) {
  state.expanded = expanded;
  for (const details of document.querySelectorAll("#conversation details")) {
    details.open = expanded;
  }
  const button = $("toggle-expand");
  button.textContent = expanded ? "collapse all" : "expand all";
  button.classList.toggle("on", expanded);
}

/* Minimal markdown renderer. Builds DOM nodes only, never HTML strings. */

function renderMarkdown(text) {
  const root = el("div", "md");
  const lines = String(text || "").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = line.match(/^\s*(```|~~~)\s*(\S*)\s*$/);
    if (fence) {
      const body = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith(fence[1])) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      const pre = el("pre", "code-block", body.join("\n"));
      if (fence[2]) pre.dataset.lang = fence[2];
      root.append(pre);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const node = el("h" + (Math.min(heading[1].length, 4) + 2));
      inline(node, heading[2]);
      root.append(node);
      index += 1;
      continue;
    }
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      root.append(el("hr"));
      index += 1;
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) {
        body.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      const quote = el("blockquote");
      quote.append(renderMarkdown(body.join("\n")));
      root.append(quote);
      continue;
    }
    if (_listItem(line)) {
      index = appendList(root, lines, index);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      index = appendTable(root, lines, index);
      continue;
    }
    const body = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !_listItem(lines[index]) &&
      !/^\s*(#{1,6}\s|>|```|~~~|\|.*\|\s*$)/.test(lines[index])
    ) {
      body.push(lines[index]);
      index += 1;
    }
    const paragraph = el("p");
    inline(paragraph, body.join("\n"));
    root.append(paragraph);
  }
  return root;
}

function _listItem(line) {
  return line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
}

function appendList(root, lines, index) {
  const stack = [];
  let last = null;
  while (index < lines.length) {
    const match = _listItem(lines[index]);
    if (!match) {
      if (last && lines[index].trim() && /^\s+/.test(lines[index])) {
        last.append(" ");
        inline(last, lines[index].trim());
        index += 1;
        continue;
      }
      break;
    }
    const depth = Math.floor(match[1].length / 2);
    const ordered = /\d/.test(match[2]);
    while (stack.length > depth + 1) stack.pop();
    if (stack.length < depth + 1 || !stack.length) {
      const list = el(ordered ? "ol" : "ul");
      (stack.length ? last || stack[stack.length - 1] : root).append(list);
      stack.push(list);
    }
    last = el("li");
    inline(last, match[3]);
    stack[stack.length - 1].append(last);
    index += 1;
  }
  return index;
}

function appendTable(root, lines, index) {
  const rows = [];
  while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
    rows.push(
      lines[index]
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim())
    );
    index += 1;
  }
  const separator = rows.length > 1 && rows[1].every((c) => /^:?-+:?$/.test(c));
  const table = el("table");
  rows.forEach((cells, rowIndex) => {
    if (separator && rowIndex === 1) return;
    const row = el("tr");
    for (const cell of cells) {
      const node = el(separator && rowIndex === 0 ? "th" : "td");
      inline(node, cell);
      row.append(node);
    }
    table.append(row);
  });
  root.append(table);
  return index;
}

function inline(target, text) {
  const pattern =
    /(`+)([\s\S]*?)\1|\*\*([^*]+)\*\*|(?<![\w*])\*([^*\n]+)\*|(?<!\w)_([^_\n]+)_|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text))) {
    if (match.index > last) target.append(text.slice(last, match.index));
    if (match[2] !== undefined) {
      target.append(el("code", "", match[2]));
    } else if (match[3] !== undefined) {
      const strong = el("strong");
      inline(strong, match[3]);
      target.append(strong);
    } else if (match[4] !== undefined || match[5] !== undefined) {
      const em = el("em");
      inline(em, match[4] ?? match[5]);
      target.append(em);
    } else {
      target.append(mdLink(match[6], match[7]));
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) target.append(text.slice(last));
}

function mdLink(label, href) {
  if (!/^https?:\/\//i.test(href)) return el("span", "", label);
  const anchor = el("a", "", label);
  anchor.href = href;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  return anchor;
}

function rawPre(value) {
  let text;
  try {
    text = JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return el("pre", "raw", text);
}

function renderArguments(args) {
  if (typeof args === "string") {
    try {
      args = JSON.parse(args);
    } catch {
      return el("pre", "raw", args);
    }
  }
  return rawPre(args);
}

function renderImage(part) {
  const mime = String(part.mimeType || "");
  if (!/^image\/[a-z0-9.+-]+$/i.test(mime) || typeof part.data !== "string") {
    return collapsible("image (not shown)", rawPre({ mimeType: part.mimeType }));
  }
  const img = el("img", "attachment");
  img.alt = "attached image";
  img.src = `data:${mime};base64,${part.data.replace(/[^A-Za-z0-9+/=]/g, "")}`;
  return collapsible("image", img);
}

/* Start */

async function init() {
  $("search").addEventListener("input", (event) => {
    state.filter = event.target.value;
    renderSessionList();
  });
  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input") || event.metaKey || event.ctrlKey) return;
    if (event.key === "e") toggleExpand();
  });
  $("toggle-expand").addEventListener("click", toggleExpand);
  try {
    state.sessions = await fetchJSON("/api/sessions");
  } catch (error) {
    $("session-list").replaceChildren(
      el("li", "session-empty", `Failed to load sessions: ${error.message}`)
    );
    return;
  }
  renderFilters();
  renderSessionList();
  const agents = new Set(state.sessions.map((s) => s.agent)).size;
  $("placeholder-stats").textContent = state.sessions.length
    ? `${state.sessions.length} sessions from ` +
      `${agents} agent${agents > 1 ? "s" : ""} in this archive`
    : "This archive holds no sessions yet.";
  if (location.hash.length > 1) {
    openSession(decodeURIComponent(location.hash.slice(1)));
  }
}

init();
