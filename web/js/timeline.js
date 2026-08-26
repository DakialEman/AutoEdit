// Línea de tiempo: dibujo de las pistas, selección y reordenación.

import {
  TRANSITION_LABELS, asset, fmtDuration, musicClips, select, state,
  textClips, totalDuration, videoClips,
} from './state.js';
import { $, clear, el } from './ui.js';

let actions = {};
let dragClipId = null;

export function initTimeline(hooks) {
  actions = hooks;

  $('#zoom-in').addEventListener('click', () => setZoom(state.zoom * 1.4));
  $('#zoom-out').addEventListener('click', () => setZoom(state.zoom / 1.4));

  const scroll = $('#timeline-scroll');
  scroll.addEventListener('click', (event) => {
    // Un clic en el fondo mueve el cursor; sobre un clip, no.
    if (event.target.closest('.clip')) return;
    const rect = $('#timeline').getBoundingClientRect();
    const seconds = (event.clientX - rect.left + scroll.scrollLeft) / state.zoom;
    actions.seek(Math.max(0, Math.min(seconds, totalDuration())));
  });

  // Rueda con Ctrl/⌘ para hacer zoom, como en cualquier editor.
  scroll.addEventListener('wheel', (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setZoom(state.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12));
  }, { passive: false });
}

function setZoom(value) {
  state.zoom = Math.max(6, Math.min(400, value));
  renderTimeline();
  renderPlayhead();
}

// ── Dibujo ──────────────────────────────────────────────────

export function renderTimeline() {
  const timeline = $('#timeline');
  const rows = clear($('#track-rows'));
  const ruler = clear($('#ruler'));
  const stats = clear($('#timeline-stats'));
  if (!state.project) return;

  const clips = videoClips();
  const total = totalDuration();
  const width = Math.max(total * state.zoom + 60, 200);
  timeline.style.width = `${width}px`;

  const summary = state.project.summary || {};
  stats.append(
    statChunk(fmtDuration(total), 'duración'),
    statChunk(String(clips.length), 'clips'),
    statChunk(String(summary.transitions ?? 0), 'transiciones'),
    statChunk(summary.resolution || '—', `${summary.fps || 30} fps`),
  );

  if (!clips.length) {
    rows.appendChild(el('div', { class: 'timeline-empty' },
      'Importa material y pulsa «Auto-editar» para generar un montaje.'));
    return;
  }

  drawRuler(ruler, total);
  rows.appendChild(videoRow(clips));
  const texts = textClips();
  if (texts.length) rows.appendChild(textRow(texts));
  const music = musicClips();
  if (music.length) rows.appendChild(musicRow(music));
}

function statChunk(value, label) {
  return el('span', {}, [el('b', {}, value), ' ', label]);
}

function drawRuler(ruler, total) {
  // Escogemos un paso que deje las etiquetas separadas al menos 64 px.
  const steps = [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  const step = steps.find((s) => s * state.zoom >= 64) || 300;
  for (let t = 0; t <= total + step; t += step) {
    const tick = el('div', { class: 'tick', style: { left: `${t * state.zoom}px` } }, [
      el('span', {}, formatTick(t)),
    ]);
    ruler.appendChild(tick);
  }

  // Marcas de pulso de la música, si el zoom da para verlas.
  const music = musicClips()[0];
  const source = music ? asset(music.asset_id) : null;
  const beats = source?.analysis?.beats || [];
  if (beats.length && state.zoom >= 24) {
    const offset = music.in_point || 0;
    for (const beat of beats) {
      const t = beat - offset;
      if (t < 0 || t > total) continue;
      ruler.appendChild(el('div', {
        class: 'tick beat',
        style: { left: `${t * state.zoom}px`, height: '6px', top: '14px' },
      }));
    }
  }
}

function formatTick(t) {
  if (t < 60) return `${Number.isInteger(t) ? t : t.toFixed(2).replace(/0$/, '')}s`;
  return `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`;
}

function videoRow(clips) {
  const row = el('div', { class: 'track-row video-row' });

  clips.forEach((clip, index) => {
    const source = asset(clip.asset_id);
    const node = el('div', {
      class: `clip ${source?.kind === 'image' ? 'image-clip' : 'video-clip'}`
        + (state.selection.type === 'clip' && state.selection.id === clip.id ? ' selected' : ''),
      style: {
        left: `${clip.start * state.zoom}px`,
        width: `${Math.max(clip.duration * state.zoom, 6)}px`,
        zIndex: String(10 + index),
      },
      draggable: 'true',
      title: `${source?.name || '?'} · ${fmtDuration(clip.duration)}`
        + (clip.transition_in.kind !== 'cut'
          ? ` · ${TRANSITION_LABELS[clip.transition_in.kind] || clip.transition_in.kind}` : ''),
      dataset: { clipId: clip.id, index: String(index) },
    });

    if (source && source.kind !== 'audio' && source.analysis?.analyzed) {
      node.appendChild(el('div', {
        class: 'clip-thumb',
        style: { backgroundImage: `url(/api/projects/${state.project.id}/assets/${source.id}/thumb)` },
      }));
    }
    node.appendChild(el('div', { class: 'clip-tint' }));

    if (clip.transition_in.kind !== 'cut' && clip.transition_in.duration > 0) {
      node.appendChild(el('div', {
        class: 'clip-transition',
        style: { width: `${Math.max(clip.transition_in.duration * state.zoom, 3)}px` },
      }));
    }
    if (clip.effect && clip.effect !== 'none' && clip.duration * state.zoom > 46) {
      node.appendChild(el('div', { class: 'clip-badge' }, '✦'));
    }
    if (clip.duration * state.zoom > 34) {
      node.appendChild(el('div', { class: 'clip-label' }, source?.name || 'sin archivo'));
    }

    node.addEventListener('click', (event) => { event.stopPropagation(); select('clip', clip.id); });
    attachDrag(node, clip, index);
    row.appendChild(node);
  });

  // Soltar un archivo de la biblioteca al final de la pista.
  row.addEventListener('dragover', (event) => {
    if (event.dataTransfer.types.includes('text/autoedit-asset')) event.preventDefault();
  });
  row.addEventListener('drop', (event) => {
    const assetId = event.dataTransfer.getData('text/autoedit-asset');
    if (!assetId) return;
    event.preventDefault();
    const rect = row.getBoundingClientRect();
    const seconds = (event.clientX - rect.left) / state.zoom;
    const index = clips.findIndex((c) => c.start + c.duration / 2 > seconds);
    actions.addClip(assetId, index < 0 ? clips.length : index);
  });
  return row;
}

function attachDrag(node, clip, index) {
  node.addEventListener('dragstart', (event) => {
    dragClipId = clip.id;
    event.dataTransfer.setData('text/autoedit-clip', clip.id);
    event.dataTransfer.effectAllowed = 'move';
    node.classList.add('dragging');
  });
  node.addEventListener('dragend', () => {
    dragClipId = null;
    node.classList.remove('dragging');
    document.querySelectorAll('.drop-before').forEach((n) => n.classList.remove('drop-before'));
  });
  node.addEventListener('dragover', (event) => {
    if (!dragClipId || dragClipId === clip.id) return;
    event.preventDefault();
    document.querySelectorAll('.drop-before').forEach((n) => n.classList.remove('drop-before'));
    node.classList.add('drop-before');
  });
  node.addEventListener('drop', (event) => {
    if (!dragClipId || dragClipId === clip.id) return;
    event.preventDefault();
    event.stopPropagation();
    node.classList.remove('drop-before');
    const from = videoClips().findIndex((c) => c.id === dragClipId);
    // Al mover hacia la derecha, el hueco de origen desplaza el destino.
    actions.moveClip(dragClipId, from < index ? index - 1 : index);
  });
}

function textRow(texts) {
  const row = el('div', { class: 'track-row text-row' });
  for (const text of texts) {
    const node = el('div', {
      class: 'clip text-clip'
        + (state.selection.type === 'text' && state.selection.id === text.id ? ' selected' : ''),
      style: {
        left: `${text.start * state.zoom}px`,
        width: `${Math.max(text.duration * state.zoom, 10)}px`,
      },
      title: text.text || '(texto vacío)',
    }, [el('div', { class: 'clip-label' }, text.text || '(vacío)')]);
    node.addEventListener('click', (event) => { event.stopPropagation(); select('text', text.id); });
    row.appendChild(node);
  }
  return row;
}

function musicRow(clips) {
  const row = el('div', { class: 'track-row music-row' });
  for (const clip of clips) {
    const source = asset(clip.asset_id);
    const node = el('div', {
      class: 'clip audio-clip'
        + (state.selection.type === 'music' && state.selection.id === clip.id ? ' selected' : ''),
      style: {
        left: `${clip.start * state.zoom}px`,
        width: `${Math.max(clip.duration * state.zoom, 10)}px`,
      },
      title: source?.name || 'música',
    });
    const wave = source?.waveform || [];
    if (wave.length) {
      const visible = Math.min(wave.length, Math.max(12, Math.floor(clip.duration * state.zoom / 3)));
      const strip = el('div', { class: 'wave' });
      const startIndex = Math.floor((clip.in_point / Math.max(source.duration, 0.01)) * wave.length);
      for (let i = 0; i < visible; i += 1) {
        const value = wave[(startIndex + Math.floor(i * wave.length / visible / 2)) % wave.length] || 0;
        strip.appendChild(el('i', { style: { height: `${Math.max(6, value * 100)}%` } }));
      }
      node.appendChild(strip);
    }
    node.appendChild(el('div', { class: 'clip-label' }, source?.name || 'música'));
    node.addEventListener('click', (event) => { event.stopPropagation(); select('music', clip.id); });
    row.appendChild(node);
  }
  return row;
}

// ── Cursor ──────────────────────────────────────────────────

export function renderPlayhead() {
  const head = $('#playhead');
  if (!head) return;
  head.style.left = `${state.playhead * state.zoom}px`;
}

/** Desplaza la vista para que el cursor siga visible durante la reproducción. */
export function followPlayhead() {
  const scroll = $('#timeline-scroll');
  const x = state.playhead * state.zoom;
  const left = scroll.scrollLeft;
  const right = left + scroll.clientWidth;
  if (x < left + 40 || x > right - 60) {
    scroll.scrollLeft = Math.max(0, x - scroll.clientWidth * 0.35);
  }
}
