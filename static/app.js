"use strict";
// All user/AI text is inserted with textContent (never innerHTML) to prevent XSS.

const $ = (s) => document.querySelector(s);
const main = $("#main");
let ME = null;
let CFG = null;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "class") n.className = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k instanceof Node ? k : String(k));
  return n;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (t.hidden = true), 4500);
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-BrandProof": "1" }, credentials: "same-origin" };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const r = await fetch(path, init);
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) {
    if (r.status === 401 && path !== "/api/login") { ME = null; renderLogin(); }
    let msg = (data && data.detail) || `Request failed (${r.status})`;
    if (Array.isArray(msg)) msg = "Please check the fields and try again.";
    const err = new Error(msg); err.status = r.status; throw err;
  }
  return data;
}

async function busy(btn, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try { return await fn(); }
  catch (e) { toast(e.message); }
  finally { btn.disabled = false; btn.textContent = old; }
}

const LABEL = { draft: "Draft", in_review: "Waiting for approval", changes_requested: "Changes requested", approved: "Approved" };
const statusBadge = (s) => el("span", { class: `badge ${s}` }, LABEL[s] || s);

// ---------- shell ----------
function setNav(view) {
  $("#nav").hidden = !ME;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  const who = $("#who");
  who.replaceChildren();
  if (ME) who.append(el("span", {}, `${ME.name} · ${ME.role}`), el("button", { class: "btn ghost small", onclick: logout }, "Sign out"));
}
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));

function go(view, arg) {
  location.hash = arg ? `${view}/${arg}` : view;
}
window.addEventListener("hashchange", route);

function route() {
  if (!ME) return renderLogin();
  const [view, arg] = location.hash.slice(1).split("/");
  setNav(view || "");
  if (view === "draft" && arg) return renderDraft(Number(arg));
  if (view === "drafts") return renderDrafts();
  if (view === "library") return renderLibrary();
  if (view === "ai") return renderAI();
  if (view === "new" && ME.role !== "reviewer") return renderNew();
  return ME.role === "reviewer" ? renderDrafts() : renderNew();
}

async function logout() {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  ME = null;
  renderLogin();
}

// ---------- login ----------
function renderLogin() {
  setNav("");
  const u = el("input", { type: "text", id: "u", autocomplete: "username", required: true });
  const p = el("input", { type: "password", id: "p", autocomplete: "current-password", required: true });
  const btn = el("button", { class: "btn", type: "submit" }, "Sign in");
  const form = el("form", { class: "card login", onsubmit: (e) => {
    e.preventDefault();
    busy(btn, async () => {
      ME = await api("/api/login", { method: "POST", body: { username: u.value, password: p.value } });
      route();
    });
  } },
    el("h1", {}, "Sign in to BrandProof"),
    el("p", { class: "sub" }, "Check content against your approved brand rules before it is published."),
    el("label", { for: "u" }, "Username"), u,
    el("label", { for: "p" }, "Password"), p,
    el("div", { class: "actions" }, btn),
  );
  if (CFG && CFG.demo) {
    const pick = (name) => el("button", { type: "button", class: "btn ghost small", onclick: () => { u.value = name; p.value = CFG.demo.password; } }, name);
    form.append(el("div", { class: "hint" },
      el("b", {}, "Demo workspace (fictional brand “Verdant”)"), el("br"),
      `Password for all demo accounts: ${CFG.demo.password}`, el("br"),
      "Fill in: ", ...CFG.demo.accounts.map(pick), el("br"),
      el("span", { class: "meta" }, "creator writes drafts · reviewer approves · admin manages the brand library")));
  }
  main.replaceChildren(form);
  u.focus();
}

// ---------- new draft ----------
function renderNew() {
  const title = el("input", { type: "text", id: "t", maxlength: 120, placeholder: "e.g. Diwali Instagram post" });
  const channel = el("select", { id: "c" }, ...[["social", "Social post"], ["ad", "Advertisement"], ["email", "Email"], ["web", "Web page"], ["document", "Document"]].map(([v, l]) => el("option", { value: v }, l)));
  const text = el("textarea", { id: "x", maxlength: 20000, placeholder: "Paste the content you want to publish…" });
  const file = el("input", { type: "file", accept: ".txt,.md,.docx", id: "f" });
  file.addEventListener("change", async () => {
    if (!file.files[0]) return;
    const fd = new FormData(); fd.append("file", file.files[0]);
    try {
      const r = await api("/api/extract", { method: "POST", form: fd });
      text.value = r.text;
      if (!title.value) title.value = file.files[0].name.replace(/\.[^.]+$/, "");
    } catch (e) { toast(e.message); }
  });
  const run = el("button", { class: "btn", onclick: () => busy(run, async () => {
    if (!title.value.trim() || !text.value.trim()) throw new Error("Add a title and some content.");
    const d = await api("/api/drafts", { method: "POST", body: { title: title.value, channel: channel.value, content: text.value } });
    sessionStorage.setItem("bp-note", d.note || "");
    go("draft", d.draft.id);
  }) }, "Run brand review");
  const sample = el("button", { class: "btn ghost", onclick: () => {
    title.value = "Launch post (sample)"; channel.value = "social"; text.value = CFG.sample;
  } }, "Use a sample draft");

  main.replaceChildren(
    el("h1", {}, "New review"),
    el("p", { class: "sub" }, "Every issue comes back with the approved rule or fact it is based on, and a suggested fix. You decide what to change."),
    el("div", { class: "grid" },
      el("div", { class: "card" },
        el("div", { class: "row" }, el("div", {}, el("label", { for: "t" }, "Title"), title), el("div", {}, el("label", { for: "c" }, "Channel"), channel)),
        el("label", { for: "x" }, "Content"), text,
        el("label", { for: "f" }, "…or upload a .txt or .docx file"), file,
        el("div", { class: "actions" }, run, sample)),
      el("div", { class: "card" },
        el("h2", {}, "How it works"),
        el("ol", { class: "steps" },
          el("li", {}, "Rule checks run on approved terminology and banned phrases."),
          el("li", {}, "The AI reviewer reads only the approved guidelines and facts that match your draft."),
          el("li", {}, "Any AI finding that cannot quote an approved source word for word is thrown away."),
          el("li", {}, "You accept, edit or dismiss each suggestion. Nothing changes automatically."),
          el("li", {}, "Submit for approval. A reviewer approves or asks for changes, and every step is logged.")),
        el("p", { class: "meta" }, CFG.ai.enabled ? `AI reviewer: ${CFG.ai.model} via ${CFG.ai.provider_host}.` : "AI reviewer is off; rule checks only."))));
}

// ---------- drafts list ----------
async function renderDrafts() {
  main.replaceChildren(el("p", { class: "empty" }, "Loading…"));
  const rows = await api("/api/drafts");
  const body = rows.length
    ? el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Title"), el("th", {}, "Channel"), el("th", {}, "Author"), el("th", {}, "Open findings"), el("th", {}, "Status"))),
        el("tbody", {}, rows.map((r) => el("tr", { class: "click", tabindex: 0, onclick: () => go("draft", r.id), onkeydown: (e) => e.key === "Enter" && go("draft", r.id) },
          el("td", {}, r.title), el("td", {}, r.channel), el("td", {}, r.author_name), el("td", {}, String(r.open_findings)), el("td", {}, statusBadge(r.status))))))
    : el("p", { class: "empty" }, ME.role === "reviewer" ? "Nothing has been submitted yet." : "No drafts yet. Start a new review.");
  main.replaceChildren(el("h1", {}, ME.role === "creator" ? "My drafts" : "All drafts"),
    el("p", { class: "sub" }, ME.role === "reviewer" ? "Open a draft waiting for approval to review it." : "Click a draft to see its findings and history."),
    el("div", { class: "card" }, body));
}

// ---------- draft detail ----------
function highlighted(content, findings, onPick) {
  const open = findings.filter((f) => f.status === "open");
  const ranges = [];
  for (const f of open) {
    const i = content.indexOf(f.excerpt);
    if (i >= 0) ranges.push([i, i + f.excerpt.length, f.id]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const out = el("div", { class: "content" });
  let pos = 0;
  for (const [s, e, id] of ranges) {
    if (s < pos) continue;
    out.append(content.slice(pos, s), el("mark", { "data-f": id, title: "See finding", onclick: () => onPick(id) }, content.slice(s, e)));
    pos = e;
  }
  out.append(content.slice(pos));
  return out;
}

async function renderDraft(id, preset) {
  let data;
  try { data = preset || await api(`/api/drafts/${id}`); }
  catch (e) { main.replaceChildren(el("p", { class: "empty" }, e.message)); return; }
  const note = data.note || sessionStorage.getItem("bp-note");
  sessionStorage.removeItem("bp-note");
  const { draft: d, findings, can } = data;
  const reload = (fresh) => renderDraft(id, fresh);
  const openN = findings.filter((f) => f.status === "open").length;

  const pick = (fid) => {
    const card = document.getElementById(`f${fid}`);
    if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.focus(); }
  };

  // left: content
  const left = el("div", {});
  const contentCard = el("div", { class: "card" }, el("h2", {}, "Content"), highlighted(d.content, findings, pick));
  if (can.edit) {
    const editBtn = el("button", { class: "btn ghost small", onclick: () => {
      const ta = el("textarea", { maxlength: 20000 }); ta.value = d.content;
      const save = el("button", { class: "btn small", onclick: () => busy(save, async () => reload(await api(`/api/drafts/${id}`, { method: "PUT", body: { content: ta.value } }))) }, "Save and re-review");
      contentCard.replaceChildren(el("h2", {}, "Edit content"), ta, el("div", { class: "actions" }, save, el("button", { class: "btn ghost small", onclick: () => reload(data) }, "Cancel")));
    } }, "Edit text");
    contentCard.append(el("div", { class: "actions" }, editBtn));
  }
  left.append(contentCard);

  // workflow
  const wf = el("div", { class: "card" }, el("h2", {}, "Approval"));
  wf.append(el("p", {}, statusBadge(d.status), " ", el("span", { class: "meta" }, `by ${d.author_name} · ${d.channel} · ${data.versions} version(s)`)));
  const acts = el("div", { class: "actions" });
  if (can.submit) {
    const b = el("button", { class: "btn", onclick: () => busy(b, async () => reload(await api(`/api/drafts/${id}/submit`, { method: "POST" }))) }, "Submit for approval");
    acts.append(b);
    if (openN) wf.append(el("p", { class: "meta" }, `${openN} finding(s) are still open. You can still submit; the reviewer will see them.`));
  }
  if (can.decide) {
    const comment = el("textarea", { maxlength: 2000, placeholder: "Comment for the author (optional)" });
    const approve = el("button", { class: "btn okb", onclick: () => busy(approve, async () => {
      let ack = false;
      if (openN) {
        ack = confirm(`${openN} finding(s) are still open. Approve anyway? This will be recorded.`);
        if (!ack) return;
      }
      reload(await api(`/api/drafts/${id}/decision`, { method: "POST", body: { decision: "approve", comment: comment.value, acknowledge_open: ack } }));
    }) }, "Approve");
    const changes = el("button", { class: "btn bad", onclick: () => busy(changes, async () => reload(await api(`/api/drafts/${id}/decision`, { method: "POST", body: { decision: "changes", comment: comment.value } }))) }, "Request changes");
    wf.append(el("label", {}, "Reviewer comment"), comment);
    acts.append(approve, changes);
  }
  if (can.resolve) {
    const rr = el("button", { class: "btn ghost", onclick: () => busy(rr, async () => reload(await api(`/api/drafts/${id}/review`, { method: "POST" }))) }, "Run review again");
    acts.append(rr);
  }
  if (d.status === "approved") wf.append(el("p", { class: "meta" }, "Approved drafts are locked."));
  wf.append(acts);
  left.append(wf);

  // comments
  const cbox = el("textarea", { maxlength: 2000, placeholder: "Add a comment" });
  const cbtn = el("button", { class: "btn small", onclick: () => busy(cbtn, async () => {
    if (!cbox.value.trim()) return;
    reload(await api(`/api/drafts/${id}/comments`, { method: "POST", body: { body: cbox.value } }));
  }) }, "Comment");
  left.append(el("div", { class: "card" }, el("h2", {}, "Comments"),
    data.comments.length ? el("ul", { class: "list" }, data.comments.map((c) => el("li", {}, el("b", {}, c.name), ": ", c.body, el("span", { class: "meta" }, ` · ${c.created_at}`)))) : el("p", { class: "meta" }, "No comments yet."),
    cbox, el("div", { class: "actions" }, cbtn)));

  // activity
  left.append(el("div", { class: "card" }, el("h2", {}, "Activity"),
    el("ul", { class: "list" }, data.audit.map((a) => el("li", {}, el("b", {}, a.name || "System"), ` ${a.action}`, a.detail ? ` — ${a.detail}` : "", el("span", { class: "meta" }, ` · ${a.created_at}`))))));

  // right: findings
  const right = el("div", {});
  if (note) right.append(el("div", { class: "note" }, note));
  right.append(el("h2", {}, `Findings (${openN} open)`));
  if (!findings.length) right.append(el("div", { class: "card empty" }, "No issues found against the approved brand sources."));
  for (const f of findings) right.append(findingCard(f, can.resolve, reload));

  main.replaceChildren(
    el("p", {}, el("a", { href: "#drafts" }, "← Drafts")),
    el("h1", {}, d.title),
    el("div", { class: "grid" }, left, right));
}

function findingCard(f, canResolve, reload) {
  const resolved = f.status !== "open";
  const card = el("div", { class: `finding${resolved ? " resolved" : ""}`, id: `f${f.id}`, tabindex: -1 },
    el("div", { class: "row" },
      el("div", {}, el("span", { class: "badge" }, f.category), " ",
        f.origin === "rule" ? el("span", { class: "badge rule" }, "rule check") : el("span", { class: `badge${f.confidence < 0.6 ? " possible" : ""}` }, f.confidence < 0.6 ? "possible issue" : "AI finding"))),
    el("p", {}, el("span", { class: "ex" }, `“${f.excerpt}”`), el("br"), f.issue),
    el("div", { class: "quote" }, el("b", {}, `Source: ${f.source_title} (${f.source_kind})`), f.source_quote));
  if (f.replacement) card.append(el("div", { class: "fix" }, el("b", {}, "Suggested: "), f.replacement));
  if (resolved) {
    card.append(el("p", { class: "meta" }, `${f.status}${f.resolution_note ? ` — ${f.resolution_note}` : ""}`));
    return card;
  }
  if (!canResolve) return card;
  const acts = el("div", { class: "actions" });
  if (f.replacement) {
    const a = el("button", { class: "btn small okb", onclick: () => busy(a, async () => reload(await api(`/api/findings/${f.id}/resolve`, { method: "POST", body: { action: "accept" } }))) }, "Accept fix");
    acts.append(a);
  }
  const e = el("button", { class: "btn small ghost", onclick: () => {
    const ta = el("textarea", { maxlength: 2000 }); ta.value = f.replacement || f.excerpt;
    const s = el("button", { class: "btn small", onclick: () => busy(s, async () => reload(await api(`/api/findings/${f.id}/resolve`, { method: "POST", body: { action: "edit", text: ta.value } }))) }, "Apply my wording");
    acts.replaceWith(el("div", { class: "inline-edit" }, el("label", {}, `Replace “${f.excerpt}” with:`), ta, el("div", { class: "actions" }, s)));
  } }, "Edit fix");
  const x = el("button", { class: "btn small ghost", onclick: () => {
    const reason = prompt("Why are you dismissing this? (optional — helps improve the guidelines)") ;
    if (reason === null) return;
    busy(x, async () => reload(await api(`/api/findings/${f.id}/resolve`, { method: "POST", body: { action: "dismiss", reason } })));
  } }, "Dismiss");
  acts.append(e, x);
  card.append(acts);
  return card;
}

// ---------- library ----------
async function renderLibrary() {
  main.replaceChildren(el("p", { class: "empty" }, "Loading…"));
  const rows = await api("/api/sources");
  const groups = { guideline: "Guidelines", fact: "Approved facts", term: "Terminology", banned: "Banned phrases" };
  const admin = ME.role === "admin";
  const parts = [el("h1", {}, "Brand library"),
    el("p", { class: "sub" }, "The only sources the reviewer is allowed to use. Every finding cites one of these.")];

  if (admin) {
    const kind = el("select", {}, Object.entries(groups).map(([v, l]) => el("option", { value: v }, l)));
    const title = el("input", { type: "text", maxlength: 120, placeholder: "Short title" });
    const body = el("textarea", { maxlength: 2000, placeholder: "The guideline, fact or reason, as it should be quoted" });
    const avoid = el("input", { type: "text", maxlength: 120, placeholder: "Wording to avoid (terms & banned phrases)" });
    const prefer = el("input", { type: "text", maxlength: 120, placeholder: "Preferred wording (terms)" });
    const add = el("button", { class: "btn", onclick: () => busy(add, async () => {
      await api("/api/sources", { method: "POST", body: { kind: kind.value, title: title.value, body: body.value, avoid: avoid.value || null, prefer: prefer.value || null } });
      toast("Added to the library."); renderLibrary();
    }) }, "Add source");
    const file = el("input", { type: "file", accept: ".txt,.md,.docx" });
    const imp = el("button", { class: "btn ghost", onclick: () => busy(imp, async () => {
      if (!file.files[0]) throw new Error("Choose a file first.");
      const fd = new FormData(); fd.append("file", file.files[0]);
      const r = await api("/api/sources/import", { method: "POST", form: fd });
      toast(`Imported ${r.imported} guideline passage(s).`); renderLibrary();
    }) }, "Import guideline document");
    parts.push(el("div", { class: "card" }, el("h2", {}, "Add to the library"),
      el("div", { class: "row" }, kind, title), el("label", {}, "Text"), body,
      el("div", { class: "row" }, avoid, prefer), el("div", { class: "actions" }, add),
      el("h2", {}, "Import a guideline document"), el("p", { class: "meta" }, "Each paragraph becomes a citable guideline passage."), file, el("div", { class: "actions" }, imp)));
  }
  for (const [k, label] of Object.entries(groups)) {
    const items = rows.filter((r) => r.kind === k);
    parts.push(el("div", { class: "card" }, el("h2", {}, `${label} (${items.length})`),
      items.length ? el("table", {}, el("tbody", {}, items.map((r) => el("tr", {},
        el("td", {}, el("b", {}, r.title), el("br"), r.body, r.avoid ? el("div", { class: "meta" }, `Avoid: “${r.avoid}”${r.prefer ? ` → use “${r.prefer}”` : ""}`) : null),
        admin ? el("td", {}, el("button", { class: "btn small ghost", onclick: async () => {
          if (!confirm(`Remove “${r.title}” from the library?`)) return;
          try { await api(`/api/sources/${r.id}`, { method: "DELETE" }); renderLibrary(); } catch (e) { toast(e.message); }
        } }, "Remove")) : null)))) : el("p", { class: "meta" }, "None yet.")));
  }
  main.replaceChildren(...parts);
}

// ---------- AI & privacy ----------
function renderAI() {
  const ai = CFG.ai;
  main.replaceChildren(el("h1", {}, "AI use and privacy"),
    el("div", { class: "card" }, el("h2", {}, "What uses AI"),
      el("ul", { class: "list" },
        el("li", {}, ai.enabled ? `Claims, tone and messaging review uses the model “${ai.model}” through ${ai.provider_host}.` : "AI review is currently switched off. Only rule checks run."),
        el("li", {}, "Terminology and banned-phrase checks are plain rules. They do not use AI."),
        el("li", {}, "Retrieval of relevant guidelines runs on this server with keyword search. No embedding service is used."))),
    el("div", { class: "card" }, el("h2", {}, "What is sent to the AI service"),
      el("ul", { class: "list" },
        el("li", {}, "The draft text you submit, and the approved guidelines and facts that match it."),
        el("li", {}, "Nothing else: no names, emails, comments or other drafts."),
        el("li", {}, "Do not submit confidential material you are not allowed to share with an external AI provider."))),
    el("div", { class: "card" }, el("h2", {}, "Safeguards"),
      el("ul", { class: "list" },
        el("li", {}, "AI findings are kept only if they quote an approved source word for word. Others are discarded."),
        el("li", {}, "Text inside a draft is treated as content, never as instructions to the reviewer."),
        el("li", {}, "People make every decision. Nothing in a draft changes unless someone accepts or edits a fix."),
        el("li", {}, "Every action is recorded in the draft's activity log, including approvals with open findings."))));
}

// ---------- boot ----------
(async () => {
  try { CFG = await api("/api/config"); } catch (_) { CFG = { demo: null, ai: { enabled: false }, sample: "" }; }
  try { ME = await api("/api/me"); } catch (_) { ME = null; }
  route();
})();
