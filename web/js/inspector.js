// Inspector: propiedades del elemento seleccionado, o ajustes generales.

import { api } from './api.js';
import {
  ASPECTS, EFFECT_LABELS, FIT_LABELS, GRADE_LABELS, TRANSITION_LABELS,
  asset, findClip, fmtDuration, musicAsset, musicClips, selectedClip, selectedText,
  state, totalDuration,
} from './state.js';
import {
  $, checkbox, clear, confirmDialog, debounce, el, field, select as selectBox,
  slider, toastError,
} from './ui.js';

let actions = {};

export function initInspector(hooks) {
  actions = hooks;
}

export function renderInspector() {
  const body = clear($('#inspector-body'));
  const title = $('#inspector-title');
  if (!state.project) { title.textContent = 'Ajustes'; return; }

  const clip = selectedClip();
  const text = selectedText();

  if (clip) { title.textContent = 'Clip'; body.append(...clipPanel(clip)); }
  else if (text) { title.textContent = 'Texto'; body.append(...textPanel(text)); }
  else if (state.selection.type === 'audio') { title.textContent = 'Audio'; body.append(...audioPanel()); }
  else { title.textContent = 'Montaje'; body.append(...globalPanel()); }
}

// ── Clip ────────────────────────────────────────────────────

function clipPanel(clip) {
  const source = asset(clip.asset_id);
  const patch = (changes) => actions.patchClip(clip.id, changes);
  const patchLive = debounce(patch, 260);
  const nodes = [];

  nodes.push(el('div', { class: 'section-title' }, 'Origen'));
  nodes.push(el('div', { style: { fontSize: '12.5px', marginBottom: '4px' } }, source?.name || 'archivo no disponible'));
  nodes.push(el('div', { class: 'hint', style: { marginBottom: '6px' } },
    source ? `${source.width}×${source.height} · ${fmtDuration(source.duration)}` : ''));

  nodes.push(field('Duración en el montaje',
    slider({
      min: 0.2, max: 12, step: 0.05, value: clip.duration,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${(+e.target.value).toFixed(2)} s`; },
      onchange: (e) => patch({ duration: +e.target.value }),
    }),
    `${clip.duration.toFixed(2)} s`));

  if (source && source.kind === 'video' && source.duration > clip.duration) {
    const maxIn = Math.max(0, source.duration - clip.duration * clip.speed);
    nodes.push(field('Punto de entrada en el original',
      slider({
        min: 0, max: maxIn, step: 0.05, value: Math.min(clip.in_point, maxIn),
        oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${(+e.target.value).toFixed(2)} s`; },
        onchange: (e) => patch({ in_point: +e.target.value }),
      }),
      `${clip.in_point.toFixed(2)} s`));
  }

  nodes.push(el('div', { class: 'section-title' }, 'Aspecto'));
  nodes.push(field('Encaje en el lienzo',
    selectBox(Object.entries(FIT_LABELS), clip.fit, (e) => patch({ fit: e.target.value }))));
  nodes.push(field('Movimiento',
    selectBox(Object.entries(EFFECT_LABELS), clip.effect, (e) => patch({ effect: e.target.value }))));
  if (clip.effect !== 'none') {
    nodes.push(field('Intensidad del movimiento',
      slider({
        min: 0.2, max: 2, step: 0.05, value: clip.effect_amount,
        oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${(+e.target.value).toFixed(2)}×`; },
        onchange: (e) => patch({ effect_amount: +e.target.value }),
      }),
      `${clip.effect_amount.toFixed(2)}×`));
  }
  nodes.push(field('Color',
    selectBox(Object.entries(GRADE_LABELS), clip.grade, (e) => patch({ grade: e.target.value }))));

  nodes.push(el('div', { class: 'section-title' }, 'Transición de entrada'));
  const transitionKind = clip.transition_in.kind;
  nodes.push(field('Tipo',
    selectBox(Object.entries(TRANSITION_LABELS), transitionKind, (e) => patch({
      transition: { kind: e.target.value, duration: clip.transition_in.duration || 0.4 },
    }))));
  if (transitionKind !== 'cut') {
    nodes.push(field('Duración',
      slider({
        min: 0.08, max: 2, step: 0.02, value: clip.transition_in.duration,
        oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${(+e.target.value).toFixed(2)} s`; },
        onchange: (e) => patch({ transition: { kind: transitionKind, duration: +e.target.value } }),
      }),
      `${clip.transition_in.duration.toFixed(2)} s`));
  }

  nodes.push(el('div', { class: 'section-title' }, 'Reproducción'));
  nodes.push(field('Velocidad',
    slider({
      min: 0.25, max: 4, step: 0.05, value: clip.speed,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${(+e.target.value).toFixed(2)}×`; },
      onchange: (e) => patch({ speed: +e.target.value }),
    }),
    `${clip.speed.toFixed(2)}×`));
  if (source?.has_audio) {
    nodes.push(field('Volumen del audio original',
      slider({
        min: 0, max: 2, step: 0.05, value: clip.volume,
        oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${Math.round(+e.target.value * 100)}%`; },
        onchange: (e) => patch({ volume: +e.target.value }),
      }),
      `${Math.round(clip.volume * 100)}%`));
  }
  nodes.push(checkbox('Reflejar horizontalmente', clip.mirror, (e) => patch({ mirror: e.target.checked })));
  nodes.push(checkbox('Bloquear (no lo toca el auto-montaje)', clip.locked, (e) => patch({ locked: e.target.checked })));

  nodes.push(el('div', { class: 'btn-row' }, [
    el('button', { class: 'ghost small', onclick: () => actions.splitAtPlayhead() }, 'Cortar aquí'),
    el('button', { class: 'ghost small', onclick: () => actions.duplicateClip(clip.id) }, 'Duplicar'),
    el('button', { class: 'ghost small danger', onclick: () => actions.deleteClip(clip.id) }, 'Eliminar'),
  ]));

  nodes.push(el('div', { class: 'section-title' }, 'Aplicar a todos'));
  nodes.push(el('div', { class: 'btn-row' }, [
    el('button', {
      class: 'ghost small',
      onclick: () => actions.applyAll({ grade: clip.grade }),
    }, 'Este color a todos'),
    el('button', {
      class: 'ghost small',
      onclick: () => actions.applyAll({ fit: clip.fit }),
    }, 'Este encaje a todos'),
    el('button', {
      class: 'ghost small',
      onclick: () => actions.applyAll({
        transition: { kind: transitionKind, duration: clip.transition_in.duration || 0.4 },
      }),
    }, 'Esta transición a todos'),
  ]));
  return nodes;
}

// ── Texto ───────────────────────────────────────────────────

function textPanel(text) {
  const patch = (changes) => actions.patchText(text.id, changes);
  const patchLive = debounce(patch, 400);
  const style = text.style;
  const setStyle = (changes) => patch({ style: { ...style, ...changes } });
  const setStyleLive = debounce(setStyle, 300);
  const nodes = [];

  nodes.push(field('Contenido',
    el('textarea', {
      value: text.text,
      placeholder: 'Escribe el texto…',
      oninput: (e) => patchLive({ text: e.target.value }),
    })));

  nodes.push(el('div', { class: 'row2' }, [
    field('Aparece en', el('input', {
      type: 'number', value: text.start.toFixed(2), step: 0.1, min: 0,
      onchange: (e) => patch({ start: +e.target.value }),
    })),
    field('Dura', el('input', {
      type: 'number', value: text.duration.toFixed(2), step: 0.1, min: 0.3,
      onchange: (e) => patch({ duration: +e.target.value }),
    })),
  ]));

  nodes.push(el('div', { class: 'section-title' }, 'Aspecto'));
  const fonts = state.fonts.length ? state.fonts.map((f) => [f.path, f.name]) : [['', 'Por defecto']];
  nodes.push(field('Tipografía',
    selectBox([['', 'Por defecto'], ...fonts], style.font, (e) => setStyle({ font: e.target.value }))));
  nodes.push(field('Tamaño',
    slider({
      min: 20, max: 160, step: 2, value: style.size,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = e.target.value; },
      onchange: (e) => setStyle({ size: +e.target.value }),
    }),
    String(style.size)));

  nodes.push(el('div', { class: 'row2' }, [
    field('Color', el('input', {
      type: 'color', value: style.color,
      onchange: (e) => setStyle({ color: e.target.value }),
    })),
    field('Contorno', el('input', {
      type: 'color', value: style.stroke_color,
      onchange: (e) => setStyle({ stroke_color: e.target.value }),
    })),
  ]));
  nodes.push(field('Grosor del contorno',
    slider({
      min: 0, max: 8, step: 1, value: style.stroke,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = e.target.value; },
      onchange: (e) => setStyle({ stroke: +e.target.value }),
    }),
    String(style.stroke)));

  nodes.push(el('div', { class: 'row2' }, [
    field('Posición horizontal', slider({
      min: 0.05, max: 0.95, step: 0.01, value: style.x,
      onchange: (e) => setStyle({ x: +e.target.value }),
    })),
    field('Posición vertical', slider({
      min: 0.05, max: 0.95, step: 0.01, value: style.y,
      onchange: (e) => setStyle({ y: +e.target.value }),
    })),
  ]));
  nodes.push(field('Alineación',
    selectBox([['left', 'Izquierda'], ['center', 'Centro'], ['right', 'Derecha']],
      style.align, (e) => setStyle({ align: e.target.value }))));
  nodes.push(field('Animación',
    selectBox([['none', 'Ninguna'], ['fade', 'Fundido'], ['pop', 'Aparición'], ['slide_up', 'Sube']],
      style.animation, (e) => setStyle({ animation: e.target.value }))));

  nodes.push(checkbox('Mayúsculas', style.uppercase, (e) => setStyle({ uppercase: e.target.checked })));
  nodes.push(checkbox('Sombra', style.shadow, (e) => setStyle({ shadow: e.target.checked })));
  nodes.push(checkbox('Caja de fondo', style.box, (e) => setStyle({ box: e.target.checked })));

  nodes.push(el('div', { class: 'btn-row' }, [
    el('button', { class: 'ghost small danger', onclick: () => actions.deleteText(text.id) }, 'Eliminar texto'),
  ]));
  return nodes;
}

// ── Música ──────────────────────────────────────────────────

function audioPanel() {
  const { track, clip } = findClip(state.selection.id);
  const timeline = state.project.timeline;
  const nodes = [];
  if (!clip || !track) return [el('div', { class: 'inspector-empty' }, 'Ese audio ya no está.')];

  const source = asset(clip.asset_id);
  const esMusica = track.kind === 'music';

  nodes.push(el('div', { style: { fontSize: '12.5px' } }, source?.name || 'audio'));
  nodes.push(el('div', { class: 'hint', style: { marginBottom: '8px' } },
    (esMusica ? 'Música del montaje' : `Pista «${track.name}»`)
    + (source?.analysis?.tempo ? ` · ${Math.round(source.analysis.tempo)} BPM` : '')));

  nodes.push(field('Volumen de este clip',
    slider({
      min: 0, max: 2, step: 0.02, value: clip.volume,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${Math.round(+e.target.value * 100)}%`; },
      onchange: (e) => actions.patchClip(clip.id, { volume: +e.target.value }),
    }),
    `${Math.round(clip.volume * 100)}%`));

  if (!esMusica) {
    nodes.push(el('div', { class: 'row2' }, [
      field('Empieza en', el('input', {
        type: 'number', value: clip.start.toFixed(2), step: 0.1, min: 0,
        onchange: (e) => actions.patchClip(clip.id, { start: +e.target.value }),
      })),
      field('Dura', el('input', {
        type: 'number', value: clip.duration.toFixed(2), step: 0.1, min: 0.1,
        onchange: (e) => actions.patchClip(clip.id, { duration: +e.target.value }),
      })),
    ]));
    nodes.push(el('div', { class: 'hint' }, 'También puedes arrastrarlo en la línea de tiempo.'));
  }

  if (source && source.duration > 0) {
    nodes.push(field('Empieza el archivo en',
      slider({
        min: 0, max: Math.max(0.1, source.duration - 0.5), step: 0.1, value: clip.in_point,
        oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${(+e.target.value).toFixed(1)} s`; },
        onchange: (e) => actions.patchClip(clip.id, { in_point: +e.target.value }),
      }),
      `${clip.in_point.toFixed(1)} s`));
  }

  nodes.push(el('div', { class: 'section-title' }, 'La pista entera'));
  nodes.push(field('Volumen de la pista',
    slider({
      min: 0, max: 2, step: 0.02, value: track.volume,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${Math.round(+e.target.value * 100)}%`; },
      onchange: (e) => actions.patchTrack(track.id, { volume: +e.target.value }),
    }),
    `${Math.round(track.volume * 100)}%`));
  nodes.push(checkbox('Silenciar la pista', track.muted,
    (e) => actions.patchTrack(track.id, { muted: e.target.checked })));

  if (esMusica) {
    nodes.push(field('Volumen general de la música',
      slider({
        min: 0, max: 1.5, step: 0.02, value: timeline.music_volume,
        oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${Math.round(+e.target.value * 100)}%`; },
        onchange: (e) => actions.patchTimeline({ music_volume: +e.target.value }),
      }),
      `${Math.round(timeline.music_volume * 100)}%`));
    nodes.push(checkbox('Bajar la música cuando suena otro audio',
      timeline.duck_music, (e) => actions.patchTimeline({ duck_music: e.target.checked })));
  }

  nodes.push(el('div', { class: 'btn-row' }, [
    el('button', { class: 'ghost small danger', onclick: () => actions.deleteClip(clip.id) },
      'Quitar este audio'),
    esMusica ? null : el('button', {
      class: 'ghost small danger', onclick: () => actions.deleteTrack(track.id),
    }, 'Borrar la pista'),
  ]));
  return nodes;
}

// ── Ajustes generales ───────────────────────────────────────

function globalPanel() {
  const project = state.project;
  const timeline = project.timeline;
  const style = project.style;
  const nodes = [];

  const problems = project.problems || [];
  if (problems.length) {
    nodes.push(el('div', { class: 'note' }, problems.join(' ')));
  }

  nodes.push(el('div', { class: 'section-title' }, 'Lienzo'));
  nodes.push(field('Formato',
    selectBox(Object.entries(ASPECTS), aspectOf(timeline), (e) => actions.setAspect(e.target.value))));
  nodes.push(el('div', { class: 'hint' },
    `${timeline.width}×${timeline.height} · ${timeline.fps} fps · ${fmtDuration(totalDuration())}`));

  nodes.push(el('div', { class: 'section-title' }, 'Audio'));
  nodes.push(field('Música',
    slider({
      min: 0, max: 1.5, step: 0.02, value: timeline.music_volume,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${Math.round(+e.target.value * 100)}%`; },
      onchange: (e) => actions.patchTimeline({ music_volume: +e.target.value }),
    }),
    `${Math.round(timeline.music_volume * 100)}%`));
  nodes.push(field('Audio original de los clips',
    slider({
      min: 0, max: 1.5, step: 0.02, value: timeline.original_audio_volume,
      oninput: (e) => { e.target.closest('.field').querySelector('b').textContent = `${Math.round(+e.target.value * 100)}%`; },
      onchange: (e) => actions.patchTimeline({ original_audio_volume: +e.target.value }),
    }),
    `${Math.round(timeline.original_audio_volume * 100)}%`));
  nodes.push(checkbox('Bajar la música cuando hay voz',
    timeline.duck_music, (e) => actions.patchTimeline({ duck_music: e.target.checked })));

  nodes.push(el('div', { class: 'section-title' }, 'Entrada y salida'));
  nodes.push(el('div', { class: 'row2' }, [
    field('Fundido de entrada', el('input', {
      type: 'number', value: timeline.fade_in, step: 0.1, min: 0, max: 5,
      onchange: (e) => actions.patchTimeline({ fade_in: +e.target.value }),
    })),
    field('Fundido de salida', el('input', {
      type: 'number', value: timeline.fade_out, step: 0.1, min: 0, max: 5,
      onchange: (e) => actions.patchTimeline({ fade_out: +e.target.value }),
    })),
  ]));

  nodes.push(el('div', { class: 'section-title' }, 'Añadir'));
  nodes.push(el('div', { class: 'btn-row' }, [
    el('button', { class: 'ghost small', onclick: () => actions.addTextAtPlayhead() }, '+ Texto aquí'),
  ]));

  nodes.push(el('div', { class: 'section-title' }, 'Estilo actual'));
  nodes.push(el('div', { class: 'hint' },
    `${style.name} · cortes de ~${style.target_clip}s · color ${GRADE_LABELS[style.grade] || style.grade}`
    + `${style.beat_sync ? ' · sincronizado con la música' : ''}`));
  if (project.prompt) {
    nodes.push(el('div', { class: 'note', style: { fontStyle: 'italic' } }, `«${project.prompt}»`));
  }

  nodes.push(el('div', { class: 'section-title' }, 'Proyecto'));
  nodes.push(el('div', { class: 'btn-row' }, [
    el('button', { class: 'ghost small', onclick: () => actions.reanalyze() }, 'Volver a analizar'),
    el('button', { class: 'ghost small', onclick: () => actions.duplicateProject() }, 'Duplicar'),
    el('button', {
      class: 'ghost small danger',
      onclick: async () => {
        const ok = await confirmDialog('Borrar proyecto',
          `Se borrará «${project.name}» y su caché de render. Tus archivos originales no se tocan.`,
          'Borrar');
        if (ok) actions.deleteProject();
      },
    }, 'Borrar'),
  ]));
  return nodes;
}

function aspectOf(timeline) {
  const ratio = timeline.width / timeline.height;
  const known = { '9:16': 9 / 16, '16:9': 16 / 9, '1:1': 1, '4:5': 4 / 5, '4:3': 4 / 3, '21:9': 21 / 9 };
  let best = '9:16';
  let bestDiff = Infinity;
  for (const [label, value] of Object.entries(known)) {
    const diff = Math.abs(ratio - value);
    if (diff < bestDiff) { best = label; bestDiff = diff; }
  }
  return best;
}
