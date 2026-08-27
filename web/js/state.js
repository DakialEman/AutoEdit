// Estado compartido de la aplicación y utilidades de formato.

const listeners = new Set();

export const state = {
  health: null,
  presets: [],
  fonts: [],
  projects: [],
  project: null,
  selection: { type: null, id: null },
  preview: { url: null, version: null, duration: 0 },
  playhead: 0,
  zoom: 64,               // píxeles por segundo en la línea de tiempo
  activeJob: null,
  interpretation: null,
  busy: false,
};

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function emit(reason = 'update') {
  for (const fn of listeners) fn(reason);
}

export function setProject(payload, reason = 'project') {
  state.project = payload;
  // La vista previa deja de valer en cuanto cambia la versión del proyecto.
  if (state.preview.url && state.preview.version !== payload.version) {
    state.preview.stale = true;
  }
  emit(reason);
}

export function select(type, id) {
  if (state.selection.type === type && state.selection.id === id) return;
  state.selection = { type, id };
  emit('selection');
}

// ── Accesos rápidos al proyecto ─────────────────────────────

export function timeline() {
  return state.project ? state.project.timeline : null;
}

export function track(kind) {
  const tl = timeline();
  return tl ? tl.tracks.find((t) => t.kind === kind) || null : null;
}

export function videoClips() {
  const t = track('video');
  return t ? [...t.clips].sort((a, b) => a.start - b.start) : [];
}

export function textClips() {
  const t = track('text');
  return t ? [...t.texts].sort((a, b) => a.start - b.start) : [];
}

/** Todas las pistas que llevan sonido: la música y las que añadas. */
export function audioTracks() {
  const tl = timeline();
  if (!tl) return [];
  return tl.tracks.filter((t) => ['music', 'voice', 'sfx'].includes(t.kind));
}

export function findClip(clipId) {
  const tl = timeline();
  if (!tl) return { track: null, clip: null };
  for (const track of tl.tracks) {
    const clip = track.clips.find((c) => c.id === clipId);
    if (clip) return { track, clip };
  }
  return { track: null, clip: null };
}

export function musicClips() {
  const t = track('music');
  return t ? [...t.clips].sort((a, b) => a.start - b.start) : [];
}

export function asset(assetId) {
  if (!state.project) return null;
  return state.project.assets.find((a) => a.id === assetId) || null;
}

export function selectedClip() {
  if (state.selection.type !== 'clip') return null;
  return videoClips().find((c) => c.id === state.selection.id) || null;
}

export function selectedText() {
  if (state.selection.type !== 'text') return null;
  return textClips().find((t) => t.id === state.selection.id) || null;
}

export function totalDuration() {
  const clips = videoClips();
  if (!clips.length) return 0;
  const last = clips[clips.length - 1];
  return last.start + last.duration;
}

export function musicAsset() {
  const clips = musicClips();
  return clips.length ? asset(clips[0].asset_id) : null;
}

// ── Formato ─────────────────────────────────────────────────

export function fmtTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function fmtDuration(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  return fmtTime(seconds);
}

export function fmtSize(bytes) {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

export const KIND_ICON = { video: '🎞️', image: '🖼️', audio: '🎵' };

export const EFFECT_LABELS = {
  none: 'Sin movimiento',
  kenburns_in: 'Zoom lento hacia dentro',
  kenburns_out: 'Zoom lento hacia fuera',
  kenburns_left: 'Paneo a la izquierda',
  kenburns_right: 'Paneo a la derecha',
  zoom_punch: 'Golpe de zoom',
  shake: 'Cámara en mano',
  slow_drift: 'Deriva suave',
};

export const GRADE_LABELS = {
  none: 'Sin corrección',
  cinematic: 'Cine',
  teal_orange: 'Teal & orange',
  warm: 'Cálido',
  cold: 'Frío',
  vintage: 'Vintage',
  vivid: 'Vivo',
  bw: 'Blanco y negro',
  faded: 'Lavado',
  night: 'Nocturno',
};

export const TRANSITION_LABELS = {
  cut: 'Corte seco',
  fade: 'Fundido',
  dissolve: 'Encadenado',
  fadeblack: 'Fundido a negro',
  fadewhite: 'Fundido a blanco',
  slideleft: 'Desliza ←',
  slideright: 'Desliza →',
  slideup: 'Desliza ↑',
  slidedown: 'Desliza ↓',
  wipeleft: 'Barrido ←',
  wiperight: 'Barrido →',
  circleopen: 'Círculo abre',
  circleclose: 'Círculo cierra',
  radial: 'Radial',
  pixelize: 'Pixelado',
  zoomin: 'Zoom',
  smoothleft: 'Suave ←',
  smoothright: 'Suave →',
  hblur: 'Desenfoque',
};

export const FIT_LABELS = {
  cover: 'Rellenar (recorta)',
  contain: 'Encajar (barras negras)',
  blur_pad: 'Encajar con fondo desenfocado',
};

export const ASPECTS = {
  '9:16': 'Vertical 9:16',
  '16:9': 'Horizontal 16:9',
  '1:1': 'Cuadrado 1:1',
  '4:5': 'Retrato 4:5',
  '4:3': 'Clásico 4:3',
  '21:9': 'Panorámico 21:9',
};
