/*
 * FamilyWall list card – one compact card per list with category headings,
 * like the FamilyWall app. Served by the familywall integration.
 *
 *   type: custom:familywall-list-card
 *   entity: todo.familywall_einkaufen
 *   title: Einkaufen          # optional, default: entity name
 *   icon: mdi:cart            # optional
 *   show_completed: false     # optional, completed section expanded
 *
 * Data: items via websocket `todo/item/subscribe`, categories from the entity
 * attributes `categories` / `item_categories` (set by the integration).
 */

const CARD_VERSION = "0.4.0";
const NO_CATEGORY = "";

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class FamilyWallListCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._items = [];
    this._editing = null; // uid of the item being edited
    this._showCompleted = false;
    this._unsub = null;
    this._drag = null;
    this._built = false;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.entities || {}).find(
      (id) => id.startsWith("todo.") && hass.entities[id].platform === "familywall",
    );
    return { entity: entity || "" };
  }

  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("todo.")) {
      throw new Error("entity (todo.familywall_…) ist erforderlich");
    }
    const changed = this._config && this._config.entity !== config.entity;
    this._config = config;
    this._showCompleted = !!config.show_completed;
    if (changed) this._resubscribe();
    if (this._built) this._renderAll();
  }

  set hass(hass) {
    const old = this._hass;
    this._hass = hass;
    if (!this._built) this._build();
    if (!this._unsub && this.isConnected) this._subscribe();
    const id = this._config.entity;
    if (!old || old.states[id] !== hass.states[id]) this._renderAll();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    this._unsubscribe();
  }

  getCardSize() {
    return 2 + Math.min(this._items.filter((i) => i.status === "needs_action").length, 12);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  // ---------- data ----------

  async _subscribe() {
    if (!this._hass || !this._config) return;
    const entity = this._config.entity;
    this._unsub = "pending";
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (msg) => {
          this._items = msg.items || [];
          this._renderLists();
        },
        { type: "todo/item/subscribe", entity_id: entity },
      );
    } catch (err) {
      this._unsub = null;
      this._error = String(err.message || err);
      this._renderLists();
    }
  }

  _unsubscribe() {
    if (typeof this._unsub === "function") this._unsub();
    this._unsub = null;
  }

  _resubscribe() {
    this._unsubscribe();
    this._items = [];
    if (this._hass && this.isConnected) this._subscribe();
  }

  get _stateObj() {
    return this._hass && this._hass.states[this._config.entity];
  }

  get _categories() {
    return (this._stateObj && this._stateObj.attributes.categories) || [];
  }

  _categoryOf(uid) {
    const map = (this._stateObj && this._stateObj.attributes.item_categories) || {};
    return map[uid] || NO_CATEGORY;
  }

  get _refreshEntity() {
    const ents = this._hass.entities || {};
    return Object.keys(ents).find((id) => id.startsWith("button.") && ents[id].platform === "familywall");
  }

  _call(domain, service, data) {
    return this._hass
      .callService(domain, service, data, { entity_id: this._config.entity })
      .catch((err) => this._toast(err.message || String(err)));
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  // ---------- rendering ----------

  _build() {
    this.shadowRoot.innerHTML = `
      <style>${FamilyWallListCard.styles}</style>
      <ha-card>
        <div class="header">
          <ha-icon class="icon"></ha-icon>
          <span class="title"></span>
          <button class="refresh" title="Jetzt aktualisieren"><ha-icon icon="mdi:refresh"></ha-icon></button>
        </div>
        <form class="add">
          <input class="new" type="text" placeholder="Eintrag hinzufügen…" enterkeyhint="done" autocomplete="off" />
          <select class="newcat" title="Kategorie"></select>
          <button class="addbtn" type="submit" title="Hinzufügen"><ha-icon icon="mdi:plus"></ha-icon></button>
        </form>
        <div class="lists"></div>
      </ha-card>`;
    const root = this.shadowRoot;
    root.querySelector(".add").addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._addItem();
    });
    root.querySelector(".refresh").addEventListener("click", () => this._refresh());
    const lists = root.querySelector(".lists");
    lists.addEventListener("click", (ev) => this._onClick(ev));
    lists.addEventListener("change", (ev) => this._onChange(ev));
    lists.addEventListener("keydown", (ev) => this._onKey(ev));
    lists.addEventListener("pointerdown", (ev) => this._dragStart(ev));
    this._built = true;
  }

  _renderAll() {
    if (!this._built || !this._config) return;
    const root = this.shadowRoot;
    const st = this._stateObj;
    root.querySelector(".title").textContent =
      this._config.title || (st && st.attributes.friendly_name) || this._config.entity;
    const icon = root.querySelector(".icon");
    icon.setAttribute("icon", this._config.icon || "mdi:format-list-checks");
    root.querySelector(".refresh").hidden = !this._refreshEntity;
    const select = root.querySelector(".newcat");
    const current = select.value;
    select.innerHTML =
      `<option value="">🏷️ Ohne Kategorie</option>` +
      this._categories.map((c) => `<option value="${esc(c.id)}">${esc(c.emoji)} ${esc(c.name)}</option>`).join("");
    select.value = current;
    select.hidden = this._categories.length === 0;
    this._renderLists();
  }

  _renderLists() {
    if (!this._built || this._editing || this._drag) return;
    const lists = this.shadowRoot.querySelector(".lists");
    if (this._error) {
      lists.innerHTML = `<div class="empty">Fehler: ${esc(this._error)}</div>`;
      return;
    }
    const open = this._items.filter((i) => i.status === "needs_action");
    const done = this._items.filter((i) => i.status === "completed");
    const groups = [{ id: NO_CATEGORY, label: "" }, ...this._categories.map((c) => ({ id: c.id, label: `${c.emoji} ${c.name}`.trim() }))];
    let html = "";
    for (const g of groups) {
      const items = open.filter((i) => this._categoryOf(i.uid) === g.id);
      if (!items.length) continue;
      html += `<div class="group" data-cat="${esc(g.id)}">`;
      if (g.label) html += `<div class="cat">${esc(g.label)}</div>`;
      html += items.map((i) => this._row(i)).join("");
      html += `</div>`;
    }
    if (!open.length) html += `<div class="empty">Alles erledigt 🎉</div>`;
    if (done.length) {
      html += `<button class="toggle-done">${this._showCompleted ? "▾" : "▸"} Erledigt (${done.length})</button>`;
      if (this._showCompleted) html += `<div class="done">${done.map((i) => this._row(i, true)).join("")}</div>`;
    }
    lists.innerHTML = html;
  }

  _row(item, done = false) {
    const desc = item.description ? `<span class="desc">${esc(item.description)}</span>` : "";
    return `
      <div class="row${done ? " is-done" : ""}" data-uid="${esc(item.uid)}">
        <input type="checkbox" class="check" ${done ? "checked" : ""} aria-label="Erledigt" />
        <span class="text">${esc(item.summary)}${desc}</span>
        ${done
          ? `<button class="del" title="Löschen"><ha-icon icon="mdi:close"></ha-icon></button>`
          : `<span class="handle" title="Verschieben"><ha-icon icon="mdi:drag-vertical"></ha-icon></span>`}
      </div>`;
  }

  _editRow(row, item) {
    const cat = this._categoryOf(item.uid);
    const options =
      `<option value="">🏷️ Ohne Kategorie</option>` +
      this._categories
        .map((c) => `<option value="${esc(c.id)}"${c.id === cat ? " selected" : ""}>${esc(c.emoji)} ${esc(c.name)}</option>`)
        .join("");
    row.classList.add("editing");
    row.innerHTML = `
      <input type="text" class="edit" value="${esc(item.summary)}" enterkeyhint="done" />
      ${this._categories.length ? `<select class="editcat">${options}</select>` : ""}
      <button class="save" title="Speichern"><ha-icon icon="mdi:check"></ha-icon></button>
      <button class="del" title="Löschen"><ha-icon icon="mdi:delete-outline"></ha-icon></button>`;
    const input = row.querySelector(".edit");
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  // ---------- actions ----------

  async _addItem() {
    const input = this.shadowRoot.querySelector(".new");
    const text = input.value.trim();
    if (!text) return;
    const category = this.shadowRoot.querySelector(".newcat").value;
    input.value = "";
    await this._call("familywall", "add_item", { item: text, ...(category ? { category_id: category } : {}) });
    input.focus();
  }

  _refresh() {
    const btn = this._refreshEntity;
    if (!btn) return;
    const el = this.shadowRoot.querySelector(".refresh");
    el.classList.add("spin");
    this._hass
      .callService("button", "press", {}, { entity_id: btn })
      .catch((err) => this._toast(err.message || String(err)))
      .finally(() => el.classList.remove("spin"));
  }

  _itemFor(el) {
    const row = el.closest(".row");
    return row ? [row, this._items.find((i) => i.uid === row.dataset.uid)] : [null, null];
  }

  _onClick(ev) {
    const target = ev.target;
    if (target.closest(".toggle-done")) {
      this._showCompleted = !this._showCompleted;
      this._renderLists();
      return;
    }
    const [row, item] = this._itemFor(target);
    if (!item) return;
    if (target.closest(".del")) {
      this._editing = null;
      this._call("todo", "remove_item", { item: item.uid });
    } else if (target.closest(".save")) {
      this._saveEdit(row, item);
    } else if (target.closest(".text") && !row.classList.contains("editing") && !this._editing) {
      this._editing = item.uid;
      this._editRow(row, item);
    }
  }

  _onChange(ev) {
    if (!ev.target.classList.contains("check")) return;
    const [, item] = this._itemFor(ev.target);
    if (!item) return;
    this._call("todo", "update_item", { item: item.uid, status: ev.target.checked ? "completed" : "needs_action" });
  }

  _onKey(ev) {
    if (!ev.target.classList.contains("edit")) return;
    const [row, item] = this._itemFor(ev.target);
    if (ev.key === "Enter") {
      ev.preventDefault();
      this._saveEdit(row, item);
    } else if (ev.key === "Escape") {
      this._editing = null;
      this._renderLists();
    }
  }

  async _saveEdit(row, item) {
    const text = row.querySelector(".edit").value.trim();
    const catSelect = row.querySelector(".editcat");
    const newCat = catSelect ? catSelect.value : this._categoryOf(item.uid);
    this._editing = null;
    if (text && text !== item.summary) await this._call("todo", "update_item", { item: item.uid, rename: text });
    if (newCat !== this._categoryOf(item.uid)) {
      // Into the new category, on top (like a new item in the app).
      await this._call("familywall", "move_item", { uid: item.uid, category_id: newCat });
    }
    this._renderLists();
  }

  // ---------- drag & drop (pointer based: mouse and touch) ----------

  _dragStart(ev) {
    const handle = ev.target.closest(".handle");
    if (!handle || this._editing) return;
    const row = handle.closest(".row");
    ev.preventDefault();
    const rect = row.getBoundingClientRect();
    const ghost = row.cloneNode(true);
    ghost.classList.add("ghost");
    ghost.style.width = `${rect.width}px`;
    ghost.style.top = `${rect.top}px`;
    ghost.style.left = `${rect.left}px`;
    this.shadowRoot.appendChild(ghost);
    row.classList.add("dragging");
    this._drag = { uid: row.dataset.uid, row, ghost, offset: ev.clientY - rect.top, target: null };
    const move = (e) => this._dragMove(e);
    const up = (e) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      this._dragEnd(e.type === "pointerup");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }

  _dragMove(ev) {
    const d = this._drag;
    d.ghost.style.top = `${ev.clientY - d.offset}px`;
    this.shadowRoot.querySelectorAll(".drop-before,.drop-after").forEach((el) => el.classList.remove("drop-before", "drop-after"));
    d.ghost.style.display = "none";
    const el = this.shadowRoot.elementFromPoint(ev.clientX, ev.clientY);
    d.ghost.style.display = "";
    const row = el && el.closest(".lists .group .row");
    const group = el && el.closest(".lists .group");
    d.target = null;
    if (row && row !== d.row) {
      const r = row.getBoundingClientRect();
      const before = ev.clientY < r.top + r.height / 2;
      row.classList.add(before ? "drop-before" : "drop-after");
      d.target = { row, before, group: row.closest(".group") };
    } else if (group && !row) {
      group.classList.add("drop-before");
      d.target = { row: null, before: true, group };
    }
  }

  async _dragEnd(drop) {
    const d = this._drag;
    this._drag = null;
    d.ghost.remove();
    d.row.classList.remove("dragging");
    this.shadowRoot.querySelectorAll(".drop-before,.drop-after").forEach((el) => el.classList.remove("drop-before", "drop-after"));
    if (!drop || !d.target) return this._renderLists();
    const { row, before, group } = d.target;
    const rows = [...group.querySelectorAll(".row")].filter((r) => r !== d.row);
    let index = row ? rows.indexOf(row) + (before ? 0 : 1) : 0;
    // previous_uid: the item directly above the drop position within the group (none = top of group).
    const previous = index > 0 ? rows[index - 1].dataset.uid : null;
    await this._call("familywall", "move_item", {
      uid: d.uid,
      category_id: group.dataset.cat,
      ...(previous ? { previous_uid: previous } : {}),
    });
    this._renderLists();
  }
}

FamilyWallListCard.styles = `
  :host { display: block; }
  ha-card { padding: 4px 0 8px; overflow: hidden; }
  .header { display: flex; align-items: center; gap: 8px; padding: 10px 12px 4px 16px; }
  .header .icon { color: var(--state-icon-color, var(--primary-color)); --mdc-icon-size: 22px; }
  .header .title { flex: 1; font-size: 1.15em; font-weight: 500; color: var(--primary-text-color); }
  button { background: none; border: 0; padding: 4px; cursor: pointer; color: var(--secondary-text-color); border-radius: 50%; display: inline-flex; }
  button:hover { color: var(--primary-color); background: var(--secondary-background-color); }
  .refresh.spin ha-icon { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .add { display: flex; align-items: center; gap: 4px; margin: 4px 12px 6px; padding: 2px 4px 2px 12px;
         border-radius: 10px; background: var(--secondary-background-color); }
  .add .new { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; padding: 9px 0;
              font: inherit; color: var(--primary-text-color); }
  select { border: 0; background: transparent; color: var(--secondary-text-color); font: inherit; font-size: 0.85em;
           max-width: 9.5em; cursor: pointer; outline: 0; }
  .add .addbtn { color: var(--primary-color); }
  .lists { padding: 0 4px; }
  .group { border-radius: 8px; }
  .group.drop-before { box-shadow: inset 0 2px 0 var(--primary-color); }
  .cat { padding: 10px 12px 2px; font-size: 0.8em; font-weight: 600; letter-spacing: 0.02em;
         color: var(--secondary-text-color); text-transform: uppercase; }
  .row { display: flex; align-items: center; gap: 10px; min-height: 36px; padding: 0 4px 0 10px;
         border-radius: 8px; position: relative; }
  .row:hover { background: var(--secondary-background-color); }
  .row.drop-before { box-shadow: inset 0 2px 0 var(--primary-color); }
  .row.drop-after { box-shadow: inset 0 -2px 0 var(--primary-color); }
  .row.dragging { opacity: 0.35; }
  .row.ghost { position: fixed; z-index: 10; pointer-events: none; background: var(--card-background-color);
               box-shadow: var(--ha-card-box-shadow, 0 4px 12px rgba(0,0,0,0.25)); opacity: 0.95; }
  .check { width: 18px; height: 18px; margin: 0; accent-color: var(--primary-color); cursor: pointer; flex: none; }
  .text { flex: 1; min-width: 0; padding: 7px 0; color: var(--primary-text-color); cursor: text; overflow-wrap: anywhere; }
  .desc { display: block; font-size: 0.8em; color: var(--secondary-text-color); }
  .is-done .text { color: var(--secondary-text-color); text-decoration: line-through; }
  .handle { color: var(--disabled-text-color, var(--secondary-text-color)); cursor: grab; touch-action: none;
            display: inline-flex; padding: 6px 2px; }
  .handle:active { cursor: grabbing; }
  .row.editing { gap: 4px; padding: 3px 4px 3px 10px; background: var(--secondary-background-color); }
  .row.editing .edit { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit;
                       color: var(--primary-text-color); padding: 6px 0; }
  .row.editing .save { color: var(--primary-color); }
  .toggle-done { border-radius: 8px; margin: 6px 4px 0; padding: 6px 8px; font: inherit; font-size: 0.9em; }
  .empty { padding: 10px 14px; color: var(--secondary-text-color); }
`;

if (!customElements.get("familywall-list-card")) {
  customElements.define("familywall-list-card", FamilyWallListCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "familywall-list-card",
    name: "FamilyWall Liste",
    description: "FamilyWall-Liste mit Kategorien, einem Eingabefeld und Drag & Drop",
    preview: false,
  });
  console.info(`%c FAMILYWALL-LIST-CARD %c ${CARD_VERSION} `, "background:#4784EC;color:#fff", "");
}
