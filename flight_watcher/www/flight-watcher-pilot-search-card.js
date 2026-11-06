/* Flight Watcher: pilot lookup card (v2, Ryan 2026-11-04). Type a last name, first name or employee number and
   press Go (or Enter): the pilot schedule card asks the Watcher for that pilot's month (read only). */
class FlightWatcherPilotSearchCard extends HTMLElement {
  setConfig(config) { this._config = { ...config }; }
  set hass(h) { this._h = h; if (!this._root) this._render(); }
  getCardSize() { return 1; }
  _go() {
    const q = this._root.querySelector("input").value.trim();
    if (!q) return;
    window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail: { q } }));
  }
  _render() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `<style>
      ha-card{padding:8px 12px;display:flex;align-items:center;gap:8px;height:100%;box-sizing:border-box}
      ha-icon{color:var(--primary-color)}
      input{flex:1;min-width:0;padding:8px 10px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font-size:14px}
      button{padding:8px 12px;border:none;border-radius:6px;background:var(--primary-color);color:#fff;font-size:13px;cursor:pointer}
    </style><ha-card><ha-icon icon="mdi:account-search"></ha-icon><input type="search" placeholder="Anybody's schedule: last name, first name or employee #"><button>Go</button></ha-card>`;
    this._root.querySelector("button").addEventListener("click", () => this._go());
    this._root.querySelector("input").addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") this._go(); });  // keep HA's e/a/c shortcuts out of the field
  }
}
customElements.define("flight-watcher-pilot-search-card", FlightWatcherPilotSearchCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilot-search-card", name: "Flight Watcher pilot lookup", description: "Look up any pilot's month" });
