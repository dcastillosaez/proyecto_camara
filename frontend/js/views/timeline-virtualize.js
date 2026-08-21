// frontend/js/views/timeline-virtualize.js
// Ventana de DOM y separadores de bloque de la linea temporal.
//
// timeline.js guarda en memoria TODOS los eventos descargados y este modulo pinta solo el
// tramo visible. Los separadores se calculan comparando cada fila con la anterior: cero red
// y cero SQL, y funcionan igual durante el scroll infinito (30-RESEARCH.md Hallazgo 9).

const DAY_MS = 864e5;

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

/** "Hoy · 18:00", "Ayer · 23:00", "12 ago · 09:00". */
export function sepLabel(ts) {
  const d = new Date(ts);
  const hour = `${String(d.getHours()).padStart(2, '0')}:00`;
  const diff = Math.round((startOfDay(new Date()) - startOfDay(d)) / DAY_MS);
  if (diff === 0) return `Hoy · ${hour}`;
  if (diff === 1) return `Ayer · ${hour}`;
  return `${d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' })} · ${hour}`;
}

/** Un solo nivel de agrupacion: cambio de hora dentro del dia, o cambio de dia. */
function sameBlock(a, b) {
  const x = new Date(a);
  const y = new Date(b);
  return x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth()
    && x.getDate() === y.getDate() && x.getHours() === y.getHours();
}

function makeSep(text) {
  const el = document.createElement('div');
  el.className = 'timeline-sep mono';
  el.textContent = text;   // texto derivado de la fecha, nunca del backend
  return el;
}

/**
 * Repinta la ventana [start, start+max) de `items` dentro de `list`, delante de `before`.
 * Devuelve el indice final pintado. No toca scrollTop: la compensacion es de quien decide
 * el nuevo `start` (timeline.js), que es quien sabe cuantas filas se han recortado.
 */
export function paintWindow({ list, before, items, start, max, makeRow }) {
  list.querySelectorAll('.timeline-row, .timeline-sep, .tl-top-sentinel').forEach((n) => n.remove());
  const end = Math.min(items.length, start + max);
  const frag = document.createDocumentFragment();
  if (start > 0) {
    // Centinela superior: al asomarse, timeline.js desliza la ventana hacia arriba
    // repintando desde memoria. Sin listener de scroll y sin cursor inverso.
    const top = document.createElement('div');
    top.className = 'tl-top-sentinel';
    top.style.height = '1px';
    frag.appendChild(top);
  }
  let prev = null;
  for (let i = start; i < end; i++) {
    const ev = items[i];
    if (prev === null || !sameBlock(prev, ev.ts)) frag.appendChild(makeSep(sepLabel(ev.ts)));
    frag.appendChild(makeRow(ev));
    prev = ev.ts;
  }
  list.insertBefore(frag, before);
  return end;
}
