/* Flight Watcher: pilot lookup card (v2, Ryan 2026-11-04). Type a last name, first name or employee number and
   press Go (or Enter): the pilot schedule card asks the Watcher for that pilot's month (read only). 1.6.2 review: on a
   pilot (state role 'pilot') the placeholder says what his lookup takes: Last name (3+ letters), Last, First, or #.
   1.7.1 (F#43): the box and Go are a form, and its submit asks: a phone keyboard's Go or Search key submits it after
   the keyboard commits what it was composing, where a keydown Enter can arrive while composing (Android with
   predictive text) and was dropped. Enter on a desktop submits the same way, so there is no keydown Enter handler
   (keydown only stops HA's shortcuts). enterkeyhint="search" puts a Search key on the phone keyboard, autocomplete is
   off, and the text is 16 px so iOS does not zoom in on a tap. The 2 s same-query guard (FW-0025) still stops a double
   tap or a held Enter from asking twice. (F#52) On a pilot's card a line above the box says it asks FLICA, and a line
   under it what a name finds, so it is not taken for the pickers list's filter below it; the placeholder is short. */
class FlightWatcherPilotSearchCard extends HTMLElement {
  setConfig(config) { this._config = { ...config }; }
  set hass(h) {
    this._h = h;
    if (!this._root) this._render();
    // 1.6.2 review: a pilot's lookup takes a last name (3+ letters), Last, First, or an employee number: no first name
    const st = h && h.states && h.states["sensor.flight_watcher_state"];
    const pilot = ((st && st.attributes) || {}).role === "pilot";
    const ph = pilot ? "Last name or employee #" : "Anybody's schedule: last name, first name or employee #";
    const inp = this._root.querySelector("input");
    if (inp.placeholder !== ph) inp.placeholder = ph;
    this._root.querySelector(".lb").hidden = !pilot;
    this._root.querySelector(".hint").hidden = !pilot;
  }
  getCardSize() { return 1; }
  _go() {  // FW-0025: one lookup per press; a double tap on Go or a held Enter inside 2 s asks once
    const q = this._root.querySelector("input").value.trim();
    if (!q) return;
    const now = Date.now();
    if (this._last && this._last.q === q && now - this._last.t >= 0 && now - this._last.t < 2000) return;
    this._last = { q, t: now };
    window.dispatchEvent(new CustomEvent("flight-watcher-pilot", { detail: { q } }));
  }
  _render() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `<style>
      ha-card{padding:8px 12px;height:100%;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center}
      form{margin:0}.row{display:flex;align-items:center;gap:8px}
      ha-icon{color:var(--primary-color)}
      .lb{display:block;font-weight:600;font-size:14px;margin:0 0 6px}
      .hint{font-size:13px;color:var(--secondary-text-color);margin:6px 0 0}
      [hidden]{display:none}
      input{flex:1;min-width:0;padding:8px 10px;border:1px solid var(--divider-color,#ccc);border-radius:6px;background:var(--card-background-color,#fff);color:var(--primary-text-color);font-size:16px}
      button{padding:8px 12px;border:none;border-radius:6px;background:var(--primary-color);color:#fff;font-size:13px;cursor:pointer;min-height:40px}
    </style><ha-card><form autocomplete="off"><label class="lb" for="q" hidden>Look up a pilot's month (asks FLICA)</label>
      <div class="row"><ha-icon icon="mdi:account-search"></ha-icon><input id="q" type="search" enterkeyhint="search" autocomplete="off" autocapitalize="words" spellcheck="false" aria-label="Look up a pilot's month" placeholder="Anybody's schedule: last name, first name or employee #"><button type="submit">Go</button></div>
      <div class="hint" hidden>An employee number finds any pilot; a whole last name (or Last, First) finds pilots on the award or seniority list on file.</div></form></ha-card>`;
    this._root.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); this._go(); });
    // keep HA's e/a/c shortcuts out of the field; Enter submits the form (implicit submission), never a keydown here
    this._root.querySelector("input").addEventListener("keydown", (e) => e.stopPropagation());
  }
}
customElements.define("flight-watcher-pilot-search-card", FlightWatcherPilotSearchCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "flight-watcher-pilot-search-card", name: "Flight Watcher pilot lookup", description: "Look up any pilot's month" });
