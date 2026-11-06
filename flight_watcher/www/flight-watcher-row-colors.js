// Flight Watcher row colors (Pako HI, HOM t1225). card-mod 4.2.1 does not attach to cards on HA 2026.10,
// so this adds the Finds table row tints to every ha-markdown shadow root directly:
// red = seat still open but gone from the pot (mdi:eye-off), green = Premium trip picked up (mdi:alpha-x).
const FW_ROW_CSS = `
tr:has(ha-icon[icon="mdi:eye-off"]) td{background-color:rgba(244,67,54,.14)}
tr:has(ha-icon[icon="mdi:alpha-x"]) td{background-color:rgba(76,175,80,.16)}
th > em{font-style:normal}
@media (max-width:700px){
  table:has(th:first-child > em){display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;font-size:11px;white-space:nowrap}
  table:has(th:first-child > em):has(th:nth-child(11)) td:nth-child(1),table:has(th:first-child > em):has(th:nth-child(11)) th:nth-child(1),
  table:has(th:first-child > em):has(th:nth-child(11)) td:last-child,table:has(th:first-child > em):has(th:nth-child(11)) th:last-child{display:none}
}`;
customElements.whenDefined("ha-markdown").then(() => {
  const C = customElements.get("ha-markdown");
  const orig = C.prototype.updated;
  C.prototype.updated = function (...a) {
    if (orig) orig.apply(this, a);
    const r = this.shadowRoot;
    if (r && !r.querySelector("style[data-flight-watcher]")) {
      const s = document.createElement("style"); s.dataset.flightWatcher = "1"; s.textContent = FW_ROW_CSS; r.appendChild(s);
    }
  };
});
