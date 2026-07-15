/**
 * Update Manager: HA sidebar panel (Phase 2, see FUTURE.md)
 *
 * Registered by panel.py via panel_custom, served as a plain ES module --
 * no build step, same convention as this project family's Lovelace cards
 * (cover-media-card.js etc.): a single file, HTMLElement + shadow DOM, no
 * bundler/npm dependency. Uses HA's own frontend components directly via
 * document.createElement + property assignment (no import needed -- they're
 * already globally registered custom elements by the time any panel loads,
 * the same reason a plain Lovelace card can use <ha-icon> unimported):
 * hass-tabs-subpage for the page chrome (the exact component /config/devices
 * and HACS's own panel use -- real per-tab URLs under this panel's own path,
 * not just in-memory tab state) and ha-form for the settings screen.
 *
 * Read-only Updates/Historie tabs, backed by websocket_api.py's
 * update_manager/updates + update_manager/install_log. Instellingen
 * replaces the interim options flow (update_manager/get_settings +
 * update_manager/save_settings) -- see FUTURE.md's "Tussenstap" note.
 *
 * Deliberately no install button anywhere yet: Update Manager doesn't call
 * update.install itself, see FUTURE.md's "Volgorde-correctie" note
 * (2026-07-15) on why rollout-pacing/install-actions wait for their own,
 * separate design discussion.
 */

// Real HA sub-routes (not just in-memory tab state): each tab gets its own
// URL under the panel's own path (e.g. /update-manager/history), navigated
// via hass-tabs-subpage the same way /config/devices etc. do -- so the
// back button, direct links, and page refresh all behave the way you'd
// expect from any other HA settings page (direct user feedback).
//
// hass-tabs-subpage's own tabs[].path must be the *full* absolute path
// (matched directly against route.prefix + route.path, and used as-is for
// the tab <a href>, see hass-tabs-subpage.ts) -- not a path relative to the
// panel, which was the bug found via live testing: tabs navigated to the
// site root (e.g. /updates) instead of /update-manager/updates.
const PANEL_PATH = "/update-manager";
const TABS = [
  { tab: "updates", relativePath: "/updates", path: `${PANEL_PATH}/updates`, name: "Updates" },
  { tab: "history", relativePath: "/history", path: `${PANEL_PATH}/history`, name: "Historie" },
  { tab: "settings", relativePath: "/settings", path: `${PANEL_PATH}/settings`, name: "Instellingen" },
];

function tabForPath(relativePath) {
  const match = TABS.find(
    (t) => relativePath === t.relativePath || relativePath.startsWith(`${t.relativePath}/`)
  );
  return match ? match.tab : "updates";
}

const PROFILE_LABELS = {
  conservative: "Behoudend",
  balanced: "Gebalanceerd",
  free: "Vrij",
  custom: "Aangepast (huidige waarden)",
};

// Plain-language explanation alongside the semver term itself -- "Patch"/
// "Minor"/"Major" mean nothing to someone who doesn't know semver, and this
// column is exactly where that distinction actually matters to a user
// (direct user feedback).
const JUMP_LABELS = {
  patch: "Patch (kleine bugfix)",
  minor: "Minor (nieuwe functie)",
  major: "Major (grote wijziging, mogelijk breaking)",
  unknown: "Onbekend versietype",
};

const STATUS_LABELS = {
  ready: "Klaar",
  waiting: "Wacht nog",
  blocked: "Handmatig",
};

// The profile picker is a select *selector* field inside the same ha-form
// as the 8 detail fields (not a plain <select>/a separate ha-select) -- one
// HA-native input component throughout, matching the pattern this project
// family's own card editors already use for selects (see cover-media-card.js
// etc.), rather than introducing a second, less-proven custom element.
function settingsSchema(profiles) {
  return [
    {
      name: "profile",
      selector: {
        select: {
          mode: "dropdown",
          options: [
            { value: "custom", label: PROFILE_LABELS.custom },
            ...Object.keys(profiles || {}).map((p) => ({ value: p, label: PROFILE_LABELS[p] || p })),
          ],
        },
      },
    },
    { name: "patch_wait_days", selector: { number: { min: 0, max: 365, mode: "box" } } },
    { name: "patch_blocked", selector: { boolean: {} } },
    { name: "minor_wait_days", selector: { number: { min: 0, max: 365, mode: "box" } } },
    { name: "minor_blocked", selector: { boolean: {} } },
    { name: "major_wait_days", selector: { number: { min: 0, max: 365, mode: "box" } } },
    { name: "major_blocked", selector: { boolean: {} } },
    { name: "unknown_wait_days", selector: { number: { min: 0, max: 365, mode: "box" } } },
    { name: "unknown_blocked", selector: { boolean: {} } },
  ];
}

// ha-data-table columns. Custom per-cell markup (an icon, a colored badge, a
// hyperlink) needs a `template` returning a real Lit TemplateResult -- not
// achievable without importing Lit, which every other file in this project
// deliberately avoids (see the module docstring). Plain values only, in
// exchange for genuine sorting/filtering and clicking the whole row through
// to the entity's real more-info dialog (`clickable` + `row-click`, which
// *is* built into ha-data-table already, no template needed for that part).
const UPDATES_TABLE_COLUMNS = {
  name: { title: "Entiteit", main: true, sortable: true, filterable: true, grows: true, minWidth: "220px" },
  version: { title: "Versie", minWidth: "180px" },
  version_jump: { title: "Type update", sortable: true, filterable: true, minWidth: "220px" },
  status: { title: "Status", sortable: true, filterable: true, minWidth: "120px" },
  available_since: { title: "Beschikbaar sinds", sortable: true, minWidth: "170px" },
  installable: { title: "Zelf installeerbaar", minWidth: "150px" },
};

const HISTORY_TABLE_COLUMNS = {
  name: { title: "Entiteit", main: true, sortable: true, filterable: true, grows: true, minWidth: "220px" },
  version: { title: "Versie", minWidth: "180px" },
  installed_at: { title: "Geïnstalleerd op", sortable: true, minWidth: "170px" },
  notes: { title: "Notities", minWidth: "220px" },
};

const SETTINGS_LABELS = {
  profile: "Begin met een profiel",
  patch_wait_days: 'Patch (kleine bugfix): dagen voor "klaar"',
  patch_blocked: "Patch (kleine bugfix): altijd handmatig",
  minor_wait_days: 'Minor (nieuwe functie): dagen voor "klaar"',
  minor_blocked: "Minor (nieuwe functie): altijd handmatig",
  major_wait_days: 'Major (grote wijziging, mogelijk breaking): dagen voor "klaar"',
  major_blocked: "Major (grote wijziging, mogelijk breaking): altijd handmatig",
  unknown_wait_days: 'Onbekend versietype: dagen voor "klaar"',
  unknown_blocked: "Onbekend versietype: altijd handmatig",
};

// HA's own relative-time display is a live-updating component
// (ha-relative-time), which can't be embedded in an ha-data-table cell
// without a Lit template (see the ha-data-table comment below) -- this is
// the same idea (age relative to now, "3 dagen geleden"), computed once per
// render instead of ticking up live.
const RELATIVE_UNITS = [
  ["jaar", "jaar", 365 * 24 * 3600],
  ["maand", "maanden", 30 * 24 * 3600],
  ["week", "weken", 7 * 24 * 3600],
  ["dag", "dagen", 24 * 3600],
  ["uur", "uur", 3600],
  ["minuut", "minuten", 60],
];

function relativeTime(iso) {
  if (!iso) return "–";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diffSec = Math.round((Date.now() - date.getTime()) / 1000);
  const future = diffSec < 0;
  const abs = Math.abs(diffSec);
  for (const [singular, plural, secondsPerUnit] of RELATIVE_UNITS) {
    const value = Math.floor(abs / secondsPerUnit);
    if (value >= 1) {
      const word = value === 1 ? singular : plural;
      return future ? `over ${value} ${word}` : `${value} ${word} geleden`;
    }
  }
  return future ? "zo dadelijk" : "zojuist";
}

function entityState(hass, entityId) {
  return hass && hass.states && hass.states[entityId];
}

// The word "update" is baked into most update entities' own friendly_name
// (e.g. "Matter Server Update") by convention -- redundant on a page that's
// entirely about updates, so drop it as a trailing suffix rather than
// showing it on every single row.
function friendlyEntityName(hass, entityId) {
  const state = entityState(hass, entityId);
  const name = (state && state.attributes && state.attributes.friendly_name) || entityId;
  return name.replace(/\s+update$/i, "");
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

class UpdateManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "updates";
    this._route = null;
    this._updates = null;
    this._installLog = null;
    this._settings = null;
    this._profiles = null;
    this._formData = null;
    this._loadError = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._initialLoad();
    } else {
      this._updateShell();
    }
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._updateShell();
  }

  // Set by HA's panel resolver on every navigation under this panel's own
  // URL (e.g. /update-manager/history) -- the same mechanism every other
  // HA settings page uses, see hass-router-page.ts/compute-route.ts.
  set route(route) {
    this._route = route;
    const path = (route && route.path) || "";
    if ((path === "" || path === "/") && route && route.prefix) {
      // Land on the Updates tab by default, same as e.g. /config redirecting
      // to its first sub-page -- don't leave the bare panel URL tab-less.
      history.replaceState(null, "", `${route.prefix}/updates`);
      this._tab = "updates";
    } else {
      this._tab = tabForPath(path);
    }
    this._updateShell();
    this._renderContent();
  }

  set panel(_panel) {}

  connectedCallback() {
    this._ensureShell();
    this._updateShell();
    this._renderContent();
  }

  async _initialLoad() {
    this._ensureShell();
    this._updateShell();
    this._renderContent();
    await this._loadAll();
    this._renderContent();
  }

  async _loadAll() {
    if (!this._hass) return;
    try {
      const [updatesResp, logResp, settingsResp] = await Promise.all([
        this._hass.callWS({ type: "update_manager/updates" }),
        this._hass.callWS({ type: "update_manager/install_log" }),
        this._hass.callWS({ type: "update_manager/get_settings" }),
      ]);
      this._updates = updatesResp.updates;
      this._installLog = logResp.entries.slice().reverse();
      this._settings = settingsResp.options;
      this._profiles = settingsResp.profiles;
      if (!this._formData) this._formData = { profile: "custom", ...this._settings };
      this._loadError = null;
    } catch (err) {
      this._loadError = (err && err.message) || String(err);
    }
  }

  async _refresh() {
    await this._loadAll();
    this._renderContent();
  }

  // Builds the page chrome once: hass-tabs-subpage, the same layout
  // component /config/devices etc. use (menu button, title, tab bar wired
  // to real HA routing) -- built once and only had its properties updated
  // afterwards, not recreated every render, so it (and any child state like
  // scroll position) survives tab switches and data refreshes.
  _ensureShell() {
    if (this._shellBuilt) return;
    this._shellBuilt = true;

    this.shadowRoot.innerHTML = `<style>${this._styles()}</style>`;

    const subpage = document.createElement("hass-tabs-subpage");
    subpage.tabs = TABS.map((t) => ({ path: t.path, name: t.name }));

    const refreshBtn = document.createElement("button");
    refreshBtn.className = "icon-btn refresh-btn";
    refreshBtn.title = "Vernieuwen";
    refreshBtn.setAttribute("slot", "toolbar-icon");
    refreshBtn.innerHTML = `<ha-icon icon="mdi:refresh"></ha-icon>`;
    refreshBtn.addEventListener("click", () => this._refresh());
    subpage.appendChild(refreshBtn);

    const content = document.createElement("div");
    content.className = "content";
    subpage.appendChild(content);

    this.shadowRoot.appendChild(subpage);
    this._subpageEl = subpage;
    this._contentEl = content;
  }

  _updateShell() {
    if (!this._subpageEl) return;
    this._subpageEl.hass = this._hass;
    this._subpageEl.narrow = this._narrow;
    this._subpageEl.route = this._route || { prefix: "", path: "" };
  }

  _renderContent() {
    if (!this._contentEl) return;
    const hasData = this._updates !== null;
    this._contentEl.innerHTML = "";
    // Tables fill the page edge-to-edge, same as /config/devices -- only
    // the settings card gets the centered/padded treatment. Without this,
    // ha-data-table's own default border (see ha-data-table.ts) combined
    // with a centered, padded wrapper made it look like a floating card
    // rather than the page itself (direct user feedback).
    this._contentEl.className = this._tab === "settings" ? "content content--form" : "content content--table";

    if (this._loadError) {
      this._contentEl.innerHTML = `<div class="error">Kon Update Manager niet laden: ${escapeHtml(this._loadError)}</div>`;
      return;
    }
    if (!hasData) {
      this._contentEl.innerHTML = `<div class="loading">Laden…</div>`;
      return;
    }

    if (this._tab === "updates") {
      this._contentEl.appendChild(this._buildUpdatesTable());
    } else if (this._tab === "history") {
      this._contentEl.appendChild(this._buildHistoryTable());
    } else {
      this._contentEl.appendChild(this._buildSettingsCard());
    }
  }

  // Opens HA's own more-info dialog for the entity -- the same one you'd
  // get by clicking it anywhere else in HA -- so working with an update
  // here feels like working with the real entity, not a separate copy of
  // its data (direct user feedback).
  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true })
    );
  }

  // ha-data-table -- the same component /config/devices, /config/entities
  // and HACS's own panel use, so sorting/filtering/column widths and the
  // overall look are genuinely native, not a hand-rolled approximation
  // (direct user feedback). One real limitation: per-cell custom markup
  // (an icon, a colored badge, a hyperlink) needs a `template` returning a
  // Lit TemplateResult, which isn't achievable without importing Lit --
  // every other file in this project deliberately has no build step/
  // dependencies, so those stay plain text for now (entity icons noted as
  // a "maybe later" in FUTURE.md/TODO-CLAUDE.md). Clicking the whole row
  // still opens the entity's real more-info dialog either way.
  // `getEntityId` resolves a clicked row's `id` to the entity_id to open
  // more-info for -- identity by default (updates table, where id already
  // *is* the entity_id), overridden by the history table (whose id must be
  // unique per log entry, since one entity can appear more than once).
  _buildDataTable(columns, rows, emptyText, getEntityId = (id) => id) {
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = emptyText;
      return empty;
    }
    const table = document.createElement("ha-data-table");
    table.hass = this._hass;
    table.narrow = this._narrow;
    table.columns = columns;
    table.data = rows;
    table.clickable = true;
    table.autoHeight = true;
    table.id = "id";
    table.addEventListener("row-click", (ev) => this._openMoreInfo(getEntityId(ev.detail.id)));
    return table;
  }

  _buildUpdatesTable() {
    const rows = this._updates.map((u) => ({
      id: u.entity_id,
      name: friendlyEntityName(this._hass, u.entity_id),
      version: `${u.installed_version} → ${u.latest_version}`,
      version_jump: JUMP_LABELS[u.version_jump] || u.version_jump,
      status: STATUS_LABELS[u.status] || u.status,
      available_since: relativeTime(u.available_since),
      installable: u.installable ? "Ja" : "Nee, alleen tonen",
    }));
    return this._buildDataTable(
      UPDATES_TABLE_COLUMNS,
      rows,
      "Geen updates die aandacht nodig hebben, alles is up-to-date."
    );
  }

  _buildHistoryTable() {
    const entityByRowId = {};
    const rows = this._installLog.map((entry) => {
      let notes = "–";
      if (entry.release_summary) {
        notes = entry.release_summary;
      } else if (entry.release_notes) {
        notes = entry.release_notes.slice(0, 200);
      } else if (entry.release_url) {
        notes = entry.release_url;
      }
      const id = `${entry.entity_id}-${entry.installed_at}`;
      entityByRowId[id] = entry.entity_id;
      return {
        id,
        name: friendlyEntityName(this._hass, entry.entity_id),
        version: `${entry.from_version} → ${entry.to_version}`,
        installed_at: formatDateTime(entry.installed_at),
        notes,
      };
    });
    return this._buildDataTable(
      HISTORY_TABLE_COLUMNS,
      rows,
      "Nog geen installaties gelogd.",
      (id) => entityByRowId[id]
    );
  }

  // ha-card + ha-progress-button, the same building blocks (and .card-content/
  // .card-actions convention) /config/general's own settings cards use --
  // verified against that page's actual source, not guessed, per direct user
  // feedback that a hand-rolled settings block didn't feel HA-native either.
  _buildSettingsCard() {
    const card = document.createElement("ha-card");
    card.outlined = true;
    card.header = "Instellingen";

    const body = document.createElement("div");
    body.className = "card-content";

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent =
      'Deze regels bepalen alleen het label (klaar / wacht nog / handmatig) op de Updates-tab en de ' +
      '"Update Manager"-sensor. Update Manager installeert nog niets zelf, in geen enkele vorm.';
    body.appendChild(hint);

    // One ha-form for the profile picker (a select *selector*, not a plain
    // <select>) and all 8 detail fields -- one HA-native input component
    // throughout, per direct user feedback, rather than a second hand-rolled
    // element next to it.
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.schema = settingsSchema(this._profiles);
    form.data = this._formData;
    form.computeLabel = (s) => SETTINGS_LABELS[s.name] ?? s.name;
    form.addEventListener("value-changed", (e) => {
      const newData = e.detail.value;
      if (newData.profile !== this._formData.profile) {
        // The profile field itself changed -- pre-fill the other 8 from
        // that preset (still fully editable afterwards), or just mark
        // "custom" without touching anything if that's what was picked.
        const preset = newData.profile !== "custom" && this._profiles && this._profiles[newData.profile];
        this._formData = preset ? { profile: newData.profile, ...preset } : newData;
      } else {
        // A detail field changed by hand -- no longer matches any preset.
        this._formData = { ...newData, profile: "custom" };
      }
      form.data = this._formData;
    });
    body.appendChild(form);
    card.appendChild(body);

    const actions = document.createElement("div");
    actions.className = "card-actions";
    const saveBtn = document.createElement("ha-progress-button");
    saveBtn.appearance = "filled";
    saveBtn.label = "Opslaan";
    saveBtn.addEventListener("click", async () => {
      saveBtn.progress = true;
      try {
        const { profile: _profile, ...settingsOnly } = this._formData;
        await this._hass.callWS({ type: "update_manager/save_settings", ...settingsOnly });
        this._settings = { ...settingsOnly };
        saveBtn.actionSuccess();
      } catch (err) {
        saveBtn.actionError();
      } finally {
        saveBtn.progress = false;
      }
    });
    actions.appendChild(saveBtn);
    card.appendChild(actions);

    return card;
  }

  _styles() {
    // Same typography tokens (--ha-font-*) this project family's other
    // cards already migrated to (see cover-media-card.js) -- so text here
    // matches HA's own scale/weight instead of arbitrary pixel values.
    return `
      :host {
        display: block; height: 100%;
        font-family: var(--ha-font-family-body, inherit);
        -webkit-font-smoothing: var(--ha-font-smoothing, antialiased);
      }
      hass-tabs-subpage { display: block; height: 100%; }

      .icon-btn {
        border: none; background: none; color: inherit; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        width: 40px; height: 40px; border-radius: 50%;
      }
      .icon-btn:hover { background: rgba(0, 0, 0, 0.05); }

      .content { display: block; }
      .content--table { padding: 0; }
      .content--form { padding: 16px; max-width: 640px; margin: 0 auto; }
      .loading, .empty {
        color: var(--secondary-text-color); padding: 32px 0; text-align: center;
        font-size: var(--ha-font-size-m, 14px);
      }
      .content--table .loading, .content--table .empty, .content--table .error { padding: 32px 16px; }
      .error { color: var(--error-color); padding: 16px 0; font-size: var(--ha-font-size-m, 14px); }
      ha-data-table { display: block; }

      ha-card { margin: 0; }
      .card-content { padding: 0 16px 16px; display: flex; flex-direction: column; }
      .card-content > *:not(:first-child) { margin-top: 16px; }
      .card-actions { display: flex; justify-content: flex-end; padding: 8px 16px 16px; }
      .hint {
        color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 13px);
        line-height: 1.4; margin: 0;
      }
      ha-form { display: block; }
    `;
  }
}

if (!customElements.get("update-manager-panel")) {
  customElements.define("update-manager-panel", UpdateManagerPanel);
}
