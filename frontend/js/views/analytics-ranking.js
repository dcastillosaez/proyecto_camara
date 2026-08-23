// frontend/js/views/analytics-ranking.js
// Tarjetas de tendencia y ranking de personas de la vista de analitica (OPS-13).
//
// Patron anti-XSS obligatorio del repo (ver timeline-row.js): plantilla `innerHTML` con
// nodos VACIOS, todo dato del servidor entra despues por textContent. El nombre de una
// persona lo escribe el operador — interpolarlo en la plantilla seria XSS almacenado
// (D-15, contraejemplo real en personGallery.js:28 que este modulo no puede copiar).
// Todo lo pintado aqui ya viene resuelto por el servidor (31-05): sin agregacion ni
// reordenacion en el navegador (OPS-14).

import { isSafeMediaUrl } from './timeline-row.js';

const $ = (id) => document.getElementById(id);

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const NO_COMPARISON_TITLE = 'No hay suficientes datos del periodo anterior para comparar.';
const TREND_COLOR = '#94a3b8'; // sin color de direccion: la flecha ya lo dice

function fmt(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${d} ${MESES[m - 1]}`;
}

// Flechas de 12px, estilo feather del repo (viewBox 24x24, stroke-width 2, sin relleno).
// Constantes del modulo: no interpolan nada.
const ARROW_UP = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/></svg>';
const ARROW_DOWN = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="7" y1="7" x2="17" y2="17"/><polyline points="17 7 17 17 7 17"/></svg>';
const ARROW_FLAT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/></svg>';

// Plantilla constante de una fila de ranking: nodos vacios, nada interpolado.
const ROW_HTML = '<span class="mono text-xs text-slate-600 w-5 text-right"></span>' +
  '<span class="rank-avatar"><img alt="" hidden><span class="rank-initial mono"></span></span>' +
  '<span class="text-xs font-semibold text-slate-200 truncate flex-1"></span>' +
  '<span class="mono text-base font-semibold text-slate-200"></span>' +
  '<span class="text-xs text-slate-500"></span>' +
  '<span class="mono text-xs text-slate-400 flex items-center gap-1"></span>';

function signedPct(deltaPct) {
  if (deltaPct === null || deltaPct === undefined) return 'sin comparación';
  if (deltaPct > 0) return `+${deltaPct} %`;
  if (deltaPct < 0) return `−${Math.abs(deltaPct)} %`;
  return `${deltaPct} %`;
}

/** Escribe las cuatro tarjetas de tendencia. summary es el payload de GET /summary. */
export function renderCards(summary) {
  const total = $('an-total-value');
  if (total) total.textContent = summary.total.toLocaleString('es-ES');

  const deltaValue = $('an-delta-value');
  if (deltaValue) {
    deltaValue.textContent = signedPct(summary.delta_pct);
    deltaValue.style.color = TREND_COLOR;
    if (summary.delta_pct === null || summary.delta_pct === undefined) {
      deltaValue.title = NO_COMPARISON_TITLE;
    } else {
      deltaValue.removeAttribute('title');
    }
  }
  const deltaRange = $('an-delta-range');
  if (deltaRange) deltaRange.textContent = `${fmt(summary.previous_range.from)} → ${fmt(summary.previous_range.to)}`;

  const peakValue = $('an-peak-value');
  if (peakValue) peakValue.textContent = summary.peak ? summary.peak.label : '—';
  const peakSupport = $('an-peak-support');
  if (peakSupport) peakSupport.textContent = summary.peak ? `${summary.peak.value} personas` : '';

  const knownValue = $('an-known-value');
  if (knownValue) knownValue.textContent = summary.known;
  const unknownSupport = $('an-unknown-support');
  if (unknownSupport) unknownSupport.textContent = `${summary.unknown} desconocidas`;
}

function paintAvatar(row, person) {
  const img = row.querySelector('img');
  const initial = row.querySelector('.rank-initial');
  if (isSafeMediaUrl(person.avatar_url)) {
    img.src = person.avatar_url;
    img.hidden = false;
    img.alt = '';
    initial.textContent = '';
  } else {
    // Nunca una imagen rota: circulo con la inicial del nombre.
    initial.textContent = (person.name || '?').charAt(0).toUpperCase();
  }
}

function paintTrend(trend, deltaPct) {
  trend.style.color = TREND_COLOR;
  if (deltaPct === null || deltaPct === undefined) {
    trend.textContent = 'sin comparación';
    trend.classList.add('text-slate-600');
    trend.title = NO_COMPARISON_TITLE;
    return;
  }
  const arrow = deltaPct > 0 ? ARROW_UP : deltaPct < 0 ? ARROW_DOWN : ARROW_FLAT;
  trend.innerHTML = arrow; // constante del modulo, sin dato del servidor
  const pct = document.createElement('span');
  pct.textContent = `${Math.abs(deltaPct)} %`;
  trend.appendChild(pct);
}

/** Repinta #an-rank-list entero. data es el payload de GET /persons. */
export function renderRanking(data) {
  const list = $('an-rank-list');
  if (!list) return;
  list.replaceChildren();

  data.persons.forEach((person, i) => {
    const row = document.createElement('div');
    row.className = 'rank-row';
    row.innerHTML = ROW_HTML;

    row.querySelector('.w-5').textContent = String(i + 1);
    paintAvatar(row, person);
    row.querySelector('.truncate').textContent = person.name;
    row.querySelector('.text-base').textContent = person.visits;
    row.querySelector('.text-slate-500').textContent = 'visitas';
    paintTrend(row.querySelector('.text-slate-400'), person.delta_pct);

    list.appendChild(row);
  });
}
