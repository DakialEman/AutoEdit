// Arranque y coordinación general de la interfaz.

import { api, followJob } from './api.js';
import { initDialogs, openExportDialog, openProjectsDialog } from './dialogs.js';
import { initInspector, renderInspector } from './inspector.js';
import { initLibrary, renderLibrary } from './library.js';
import {
  emit, fmtTime, musicClips, select, selectedClip, setProject, state,
  subscribe, totalDuration, videoClips,
} from './state.js';
import { followPlayhead, initTimeline, renderPlayhead, renderTimeline } from './timeline.js';
import { $, clear, debounce, el, initModal, toast, toastError } from './ui.js';

const LAST_PROJECT_KEY = 'autoedit.lastProject';
let video = null;
let analysisWatcher = null;

// ── Acciones ────────────────────────────────────────────────

const actions = {
  onProjectChanged(payload) { setProject(payload); },

  async openProject(id) {
    try {
      const payload = await api.project(id);
      localStorage.setItem(LAST_PROJECT_KEY, id);
      resetPreview();
      select(null, null);
      setProject(payload, 'open');
      refreshProjectName();
      $('#prompt').value = payload.prompt || '';
      autosizePrompt();
      actions.watchAnalysis();
    } catch (error) { toastError(error); }
  },

  async createProject(name) {
    try {
      const payload = await api.createProject(name || '');
      localStorage.setItem(LAST_PROJECT_KEY, payload.id);
      resetPreview();
      setProject(payload, 'open');
      refreshProjectName();
      $('#prompt').value = '';
      toast('Proyecto creado', 'ok');
    } catch (error) { toastError(error); }
  },

  async duplicateProject() {
    try {
      const payload = await api.duplicateProject(state.project.id);
      localStorage.setItem(LAST_PROJECT_KEY, payload.id);
      resetPreview();
      setProject(payload, 'open');
      refreshProjectName();
      toast('Proyecto duplicado', 'ok');
    } catch (error) { toastError(error); }
  },

  async deleteProject() {
    const id = state.project.id;
    try {
      await api.deleteProject(id);
      localStorage.removeItem(LAST_PROJECT_KEY);
      const { projects } = await api.projects();
      if (projects.length) await actions.openProject(projects[0].id);
      else await actions.createProject('');
      toast('Proyecto borrado', 'ok');
    } catch (error) { toastError(error); }
  },

  async patchProject(body) {
    try { setProject(await api.patchProject(state.project.id, body)); }
    catch (error) { toastError(error); }
  },

  /** Devuelve el proyecto a un estado anterior (botón «Deshacer»). */
  async restoreSnapshot(snapshot) {
    try {
      setProject(await api.patchProject(state.project.id, snapshot));
      toast('Restaurado', 'ok');
    } catch (error) { toastError(error); }
  },

  async patchTimeline(changes) {
    const timeline = { ...state.project.timeline, ...changes };
    await actions.patchProject({ timeline });
  },

  async setAspect(aspect) {
    // Cambiar el formato rehace el lienzo, así que se vuelve a montar con el
    // mismo estilo: es lo que espera cualquiera al pasar de vertical a horizontal.
    try {
      const style = { ...state.project.style, aspect };
      await api.patchProject(state.project.id, { style });
      if (videoClips().length) {
        const payload = await api.autoedit(state.project.id, {
          prompt: state.project.prompt || '',
          preset: null,
          engine: 'heuristic',
        });
        setProject(payload);
        toast(`Formato cambiado a ${aspect}`, 'ok');
      } else {
        setProject(await api.project(state.project.id));
      }
    } catch (error) { toastError(error); }
  },

  async autoedit(preset = null) {
    if (!state.project) return;
    if (!state.project.assets.length) { toast('Primero importa algún vídeo o foto'); return; }
    setBusy(true);
    try {
      const payload = await api.autoedit(state.project.id, {
        prompt: $('#prompt').value,
        preset,
        engine: state.health?.prompt_engines?.includes('ollama') ? 'auto' : 'heuristic',
      });
      state.interpretation = payload.interpretation;
      resetPreview();
      select(null, null);
      setProject(payload);
      toast(`Montaje generado: ${payload.summary.clips} clips, ${payload.summary.duration.toFixed(1)}s`, 'ok');
    } catch (error) { toastError(error); }
    finally { setBusy(false); }
  },

  async reshuffle() {
    setBusy(true);
    try {
      setProject(await api.reshuffle(state.project.id));
      toast('Nueva combinación', 'ok');
    } catch (error) { toastError(error); }
    finally { setBusy(false); }
  },

  async patchClip(clipId, changes) {
    try { setProject(await api.patchClip(state.project.id, clipId, changes)); }
    catch (error) { toastError(error); }
  },
  async moveClip(clipId, index) {
    try { setProject(await api.moveClip(state.project.id, clipId, index)); }
    catch (error) { toastError(error); }
  },
  async duplicateClip(clipId) {
    try { setProject(await api.duplicateClip(state.project.id, clipId)); }
    catch (error) { toastError(error); }
  },
  async deleteClip(clipId) {
    try {
      select(null, null);
      setProject(await api.deleteClip(state.project.id, clipId));
    } catch (error) { toastError(error); }
  },
  async addClip(assetId, index = null) {
    try {
      const payload = await api.addClip(state.project.id, { asset_id: assetId, index });
      setProject(payload);
      toast('Clip añadido', 'ok');
    } catch (error) { toastError(error); }
  },
  async applyAll(changes) {
    try {
      setProject(await api.applyAll(state.project.id, changes));
      toast('Aplicado a todos los clips', 'ok');
    } catch (error) { toastError(error); }
  },

  splitAtPlayhead() {
    const at = state.playhead;
    const clip = videoClips().find((c) => at > c.start + 0.1 && at < c.start + c.duration - 0.1);
    if (!clip) { toast('Coloca el cursor dentro de un clip para cortarlo'); return; }
    api.splitClip(state.project.id, clip.id, at)
      .then((payload) => { setProject(payload); toast('Clip cortado', 'ok'); })
      .catch(toastError);
  },

  async addTextAtPlayhead() {
    try {
      const payload = await api.addText(state.project.id, {
        text: 'Texto nuevo',
        start: state.playhead,
        duration: 2.5,
      });
      setProject(payload);
      const texts = payload.timeline.tracks.find((t) => t.kind === 'text')?.texts || [];
      const last = texts[texts.length - 1];
      if (last) select('text', last.id);
    } catch (error) { toastError(error); }
  },
  async patchText(textId, changes) {
    try { setProject(await api.patchText(state.project.id, textId, changes)); }
    catch (error) { toastError(error); }
  },
  async deleteText(textId) {
    try {
      select(null, null);
      setProject(await api.deleteText(state.project.id, textId));
    } catch (error) { toastError(error); }
  },

  async addTrack() {
    try {
      setProject(await api.addTrack(state.project.id, ''));
      toast('Pista de audio añadida. Arrastra un audio de la izquierda a esa fila.', 'ok', 6000);
    } catch (error) { toastError(error); }
  },
  async patchTrack(trackId, changes) {
    try { setProject(await api.patchTrack(state.project.id, trackId, changes)); }
    catch (error) { toastError(error); }
  },
  async deleteTrack(trackId) {
    try {
      select(null, null);
      setProject(await api.deleteTrack(state.project.id, trackId));
      toast('Pista borrada', 'ok');
    } catch (error) { toastError(error); }
  },
  async addAudioClip(trackId, assetId, start) {
    try {
      setProject(await api.addTrackClip(state.project.id, trackId, assetId, start));
      toast('Audio colocado', 'ok');
    } catch (error) { toastError(error); }
  },

  async setMusic(assetId) {
    try {
      setProject(await api.setMusic(state.project.id, assetId));
      toast(assetId ? 'Música asignada' : 'Música quitada', 'ok');
    } catch (error) { toastError(error); }
  },
  async setMusicIn(inPoint) {
    const timeline = structuredClone(state.project.timeline);
    const track = timeline.tracks.find((t) => t.kind === 'music');
    if (!track || !track.clips.length) return;
    track.clips[0].in_point = inPoint;
    await actions.patchProject({ timeline });
  },

  async reanalyze() {
    try {
      const { job_id: jobId } = await api.analyze(state.project.id, true);
      toast('Analizando el material…');
      watchJob(jobId, async () => {
        setProject(await api.project(state.project.id));
      });
    } catch (error) { toastError(error); }
  },

  watchAnalysis() {
    // Tras importar, el servidor analiza en segundo plano: refrescamos cuando
    // acabe para que aparezcan miniaturas, duraciones y pulsos.
    clearTimeout(analysisWatcher);
    analysisWatcher = setTimeout(async () => {
      try {
        const { jobs } = await api.get(`/api/jobs?project_id=${state.project.id}&active=true`);
        const job = jobs.find((j) => j.kind === 'analyze');
        if (job) watchJob(job.id, async () => { setProject(await api.project(state.project.id)); });
      } catch { /* sin trabajos activos */ }
    }, 400);
  },

  seek(seconds) {
    state.playhead = seconds;
    if (video && video.duration) video.currentTime = Math.min(seconds, video.duration - 0.03);
    renderPlayhead();
    updateTransport();
  },

  onJobTick(job) { showJob(job); },
  onExportDone() { api.project(state.project.id).then(setProject).catch(() => {}); },
};

// ── Vista previa ────────────────────────────────────────────

function resetPreview() {
  state.preview = { url: null, version: null, duration: 0, stale: false };
  if (video) { video.removeAttribute('src'); video.load(); video.classList.remove('ready'); }
  $('#viewer-empty').hidden = false;
  $('#viewer-stale').hidden = true;
  state.playhead = 0;
  updateTransport();
}

async function makePreview() {
  if (!state.project) return;
  if (!videoClips().length) { toast('No hay nada que previsualizar todavía'); return; }
  setBusy(true);
  try {
    const { job_id: jobId } = await api.render(state.project.id, true);
    const result = await followJob(jobId, showJob);
    const url = `/api/projects/${state.project.id}/file`
      + `?path=${encodeURIComponent(result.path)}&v=${Date.now()}`;
    state.preview = {
      url, version: state.project.version, duration: result.duration, stale: false,
    };
    video.src = url;
    video.classList.add('ready');
    $('#viewer-empty').hidden = true;
    $('#viewer-stale').hidden = true;
    for (const warning of result.warnings || []) toast(warning);
    updateTransport();
  } catch (error) {
    if (String(error.message) !== 'Cancelado') toastError(error);
  } finally {
    setBusy(false);
    hideJob();
  }
}

function updateTransport() {
  const total = state.preview.duration || totalDuration();
  $('#time-total').textContent = fmtTime(total);
  $('#time-current').textContent = fmtTime(state.playhead);
  const scrub = $('#scrub');
  scrub.value = total ? String(Math.round((state.playhead / total) * 1000)) : '0';
  $('#btn-play').textContent = video && !video.paused && !video.ended ? '❚❚' : '▶';
}

// ── Trabajos ────────────────────────────────────────────────

let currentJobId = null;

function showJob(job) {
  currentJobId = job.id;
  state.activeJob = job;
  $('#job-strip').hidden = false;
  $('#job-label').textContent = job.message || job.kind;
  $('#job-fill').style.width = `${Math.round(job.progress * 100)}%`;
}

function hideJob() {
  currentJobId = null;
  state.activeJob = null;
  $('#job-strip').hidden = true;
}

async function watchJob(jobId, onDone) {
  try {
    await followJob(jobId, showJob);
    if (onDone) await onDone();
  } catch (error) {
    if (String(error.message) !== 'Cancelado') toastError(error);
  } finally {
    hideJob();
  }
}

function setBusy(busy) {
  state.busy = busy;
  for (const id of ['#btn-autoedit', '#btn-preview', '#btn-export', '#btn-reshuffle']) {
    $(id).disabled = busy;
  }
}

// ── Estilos ─────────────────────────────────────────────────

function renderStyleStrip() {
  const strip = clear($('#style-strip'));
  const currentId = state.project?.style?.id;
  for (const preset of state.presets) {
    const chip = el('button', {
      class: `style-chip${preset.id === currentId ? ' active' : ''}`,
      title: preset.description,
      onclick: () => actions.autoedit(preset.id),
    }, [el('span', {}, preset.emoji), el('span', {}, preset.name)]);
    strip.appendChild(chip);
  }
}

function renderUnderstood() {
  const box = $('#understood');
  const interpretation = state.interpretation;
  if (!interpretation || (!interpretation.understood?.length && !interpretation.ignored?.length)) {
    box.hidden = true;
    return;
  }
  clear(box);
  box.hidden = false;
  for (const item of interpretation.understood || []) {
    box.appendChild(el('span', { class: 'tag' }, `✓ ${item}`));
  }
  if (interpretation.ignored?.length) {
    box.appendChild(el('span', { class: 'tag muted' },
      `sin aplicar: ${interpretation.ignored.join(', ')}`));
  }
}

// ── Render general ──────────────────────────────────────────

function renderAll(reason) {
  if (reason !== 'selection') {
    renderLibrary();
    renderTimeline();
    renderStyleStrip();
    renderUnderstood();
    updateStale();
  } else {
    renderTimeline();
  }
  renderInspector();
  renderPlayhead();
  updateTransport();
}

function updateStale() {
  const stale = !!(state.preview.url && state.preview.version !== state.project?.version);
  $('#viewer-stale').hidden = !stale;
}

function refreshProjectName() {
  $('#project-name').value = state.project?.name || '';
}

function autosizePrompt() {
  const node = $('#prompt');
  node.style.height = 'auto';
  node.style.height = `${Math.min(node.scrollHeight, 110)}px`;
}

// ── Atajos de teclado ───────────────────────────────────────

function initShortcuts() {
  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const typing = target.matches('input, textarea, select') || target.isContentEditable;
    if (typing) {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && target.id === 'prompt') {
        event.preventDefault();
        actions.autoedit();
      }
      return;
    }
    if (!$('#modal-backdrop').hidden) return;

    if (event.code === 'Space') { event.preventDefault(); togglePlay(); }
    else if (event.key === 's' || event.key === 'S') { event.preventDefault(); actions.splitAtPlayhead(); }
    else if (event.key === 'f' || event.key === 'F') { event.preventDefault(); toggleFullscreen(); }
    else if (event.key === 'Delete' || event.key === 'Backspace') {
      const clip = selectedClip();
      if (clip) { event.preventDefault(); actions.deleteClip(clip.id); }
      else if (state.selection.type === 'text') { event.preventDefault(); actions.deleteText(state.selection.id); }
    } else if (event.key === 'ArrowLeft') { actions.seek(Math.max(0, state.playhead - (event.shiftKey ? 1 : 1 / 30))); }
    else if (event.key === 'ArrowRight') {
      const total = state.preview.duration || totalDuration();
      actions.seek(Math.min(total, state.playhead + (event.shiftKey ? 1 : 1 / 30)));
    } else if (event.key === 'Escape') { select(null, null); }
  });
}

function toggleFullscreen() {
  const stage = $('#stage');
  const active = document.fullscreenElement || document.webkitFullscreenElement;
  if (active) {
    (document.exitFullscreen || document.webkitExitFullscreen).call(document);
  } else {
    const request = stage.requestFullscreen || stage.webkitRequestFullscreen;
    if (!request) { toast('Tu navegador no permite pantalla completa aquí'); return; }
    request.call(stage).catch((error) => toastError(error));
  }
}

function syncFullscreenButton() {
  const active = !!(document.fullscreenElement || document.webkitFullscreenElement);
  const button = $('#btn-fullscreen');
  button.textContent = active ? '⛶' : '⛶';
  button.title = active ? 'Salir de pantalla completa (Esc)' : 'Pantalla completa (F)';
}

function togglePlay() {
  if (!video || !video.src) { makePreview(); return; }
  if (video.paused) video.play(); else video.pause();
  updateTransport();
}

// ── Arranque ────────────────────────────────────────────────

async function boot() {
  initModal();
  initLibrary(actions);
  initTimeline(actions);
  initInspector(actions);
  initDialogs(actions);
  initShortcuts();

  video = $('#preview-video');
  video.addEventListener('timeupdate', () => {
    state.playhead = video.currentTime;
    renderPlayhead();
    updateTransport();
    if (!video.paused) followPlayhead();
  });
  video.addEventListener('play', updateTransport);
  video.addEventListener('pause', updateTransport);
  video.addEventListener('ended', updateTransport);

  $('#btn-play').addEventListener('click', togglePlay);
  $('#scrub').addEventListener('input', (event) => {
    const total = state.preview.duration || totalDuration();
    actions.seek((+event.target.value / 1000) * total);
  });

  $('#btn-autoedit').addEventListener('click', () => actions.autoedit());
  $('#btn-reshuffle').addEventListener('click', () => actions.reshuffle());
  $('#btn-split').addEventListener('click', () => actions.splitAtPlayhead());
  $('#btn-preview').addEventListener('click', makePreview);
  $('#btn-make-preview').addEventListener('click', makePreview);
  $('#btn-refresh-preview').addEventListener('click', makePreview);
  $('#btn-add-track').addEventListener('click', () => actions.addTrack());
  $('#btn-fullscreen').addEventListener('click', toggleFullscreen);
  for (const evento of ['fullscreenchange', 'webkitfullscreenchange']) {
    document.addEventListener(evento, syncFullscreenButton);
  }
  $('#btn-export').addEventListener('click', openExportDialog);
  $('#btn-projects').addEventListener('click', openProjectsDialog);
  $('#job-cancel').addEventListener('click', () => {
    if (currentJobId) api.cancelJob(currentJobId).catch(() => {});
  });

  const promptNode = $('#prompt');
  promptNode.addEventListener('input', autosizePrompt);
  promptNode.addEventListener('change', debounce(() => {
    if (state.project) api.patchProject(state.project.id, { prompt: promptNode.value }).catch(() => {});
  }, 600));

  $('#project-name').addEventListener('change', (event) => {
    if (state.project) actions.patchProject({ name: event.target.value });
  });

  subscribe(renderAll);

  try {
    const [health, styles, fonts] = await Promise.all([api.health(), api.styles(), api.fonts()]);
    state.health = health;
    state.presets = styles.presets;
    state.fonts = fonts.fonts;
    if (!health.ok) {
      toast(health.ffmpeg_error || 'No se ha encontrado FFmpeg', 'error', 20000);
    }
    if (health.fonts && !health.fonts.count) {
      toast('No se han encontrado tipografías: los textos usarán una fuente básica.', '', 9000);
    }
  } catch (error) {
    toastError(error);
  }

  try {
    const { projects } = await api.projects();
    state.projects = projects;
    const last = localStorage.getItem(LAST_PROJECT_KEY);
    if (last && projects.some((p) => p.id === last)) await actions.openProject(last);
    else if (projects.length) await actions.openProject(projects[0].id);
    else await actions.createProject('');
  } catch (error) {
    toastError(error);
  }
  emit('boot');
}

boot();
