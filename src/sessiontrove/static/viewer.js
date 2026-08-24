"use strict";

/* All transcript content is rendered with textContent, never innerHTML. */

const state = { sessions: [], filter: "", session: null, activeLeaf: null };

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

/* Session list */

function sessionTitle(summary) {
  const cwd = summary.cwd || summary.name || summary.id;
  return cwd.split("/").filter(Boolean).pop() || cwd;
}

function renderSessionList() {
  const list = $("session-list");
  list.replaceChildren();
  const needle = state.filter.trim().toLowerCase();
  for (const summary of state.sessions) {
    const haystack = [summary.cwd, summary.preview, summary.machine, summary.name]
      .join(" ")
      .toLowerCase();
    if (needle && !haystack.includes(needle)) continue;
    const item = el("li", "session-item");
    if (state.session && state.session.id === summary.id) {
      item.classList.add("active");
    }
    item.append(el("div", "session-title", sessionTitle(summary)));
    const line = el("div", "session-sub");
    line.append(el("span", "", fmtDate(summary.started)));
    if (summary.machine) line.append(el("span", "chip", summary.machine));
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
    if (record.kind === "user" && firstText(record)) return firstText(record);
  }
  for (const record of segment.records) {
    if (firstText(record)) return firstText(record);
  }
  return segment.records[0].kind || "records";
}

function renderBranches(session) {
  const nav = $("branches");
  nav.replaceChildren();
  const leaves = session.records.filter(
    (record) => !(session.children.get(record.id) || []).length
  );
  nav.hidden = leaves.length < 2;
  if (nav.hidden) return;
  nav.append(el("div", "branches-title", `Branches (${leaves.length})`));
  nav.append(renderSegments(session, segmentsFrom(session, session.children.get(null) || [])));
}

function renderSegments(session, segments) {
  const list = el("ul", "segments");
  const active = new Set(pathTo(session, state.activeLeaf).map((r) => r.id));
  for (const segment of segments) {
    const item = el("li");
    const button = el("button", "segment");
    if (segment.records.some((record) => active.has(record.id))) {
      button.classList.add("active");
    }
    button.append(
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
  meta.append(el("h2", "", session.meta.cwd || session.id));
  const facts = el("div", "facts");
  const add = (label, value) => {
    if (value === undefined || value === null || value === "") return;
    const fact = el("span", "fact");
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
  add("file", session.id);
  add("session", session.meta.session_id);
  meta.append(facts);
}

/* Conversation */

function renderConversation(session) {
  const container = $("conversation");
  container.replaceChildren();
  for (const record of pathTo(session, state.activeLeaf)) {
    container.append(renderRecord(record));
  }
  if (!container.children.length) {
    container.append(el("p", "session-empty", "No records."));
  }
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
  if (record.timestamp) head.append(el("time", "", fmtDate(record.timestamp)));
  card.append(head);
  appendParts(card, record.parts || []);
  return card;
}

function renderToolResult(record) {
  const card = el("article", "record tool-result" + (record.isError ? " error" : ""));
  const body = el("div", "tool-body");
  appendParts(body, record.parts || []);
  const label =
    (record.isError ? "tool error: " : "tool result: ") + (record.toolName || "?");
  card.append(collapsible(label, body));
  return card;
}

function renderCompaction(record) {
  const card = el("article", "record system");
  const label =
    "compaction" +
    (record.tokensBefore ? ` (${record.tokensBefore} tokens before)` : "");
  card.append(collapsible(label, el("div", "text", record.summary || "")));
  return card;
}

function renderRaw(record, label, raw) {
  const card = el("article", "record system");
  card.append(collapsible(label, rawPre(raw)));
  return card;
}

function appendParts(target, parts) {
  for (const part of parts) {
    if (part.type === "text") {
      target.append(el("div", "text", part.text || ""));
    } else if (part.type === "thinking") {
      target.append(collapsible("reasoning", el("div", "text thinking", part.text || "")));
    } else if (part.type === "tool_call") {
      target.append(
        collapsible(`tool call: ${part.name || "?"}`, renderArguments(part.arguments))
      );
    } else if (part.type === "image") {
      target.append(renderImage(part));
    } else {
      target.append(collapsible("unknown content", rawPre(part.raw ?? part)));
    }
  }
}

function collapsible(label, body) {
  const details = el("details", "collapsible");
  details.append(el("summary", "", label));
  details.append(body);
  return details;
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
  try {
    state.sessions = await fetchJSON("/api/sessions");
  } catch (error) {
    $("session-list").replaceChildren(
      el("li", "session-empty", `Failed to load sessions: ${error.message}`)
    );
    return;
  }
  renderSessionList();
  if (location.hash.length > 1) {
    openSession(decodeURIComponent(location.hash.slice(1)));
  }
}

init();
