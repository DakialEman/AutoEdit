// Panel de material: importación, listado y gestión de los archivos.

import { api, followJob } from './api.js';
import {
  KIND_ICON, asset, fmtDuration, fmtSize, musicAsset, state,
} from './state.js';
import { $, clear, closeModal, confirmDialog, el, openModal, toast, toastError } from './ui.js';

let actions = {};

export function initLibrary(hooks) {
  actions = hooks;

  const dropzone = $('#dropzone');
  const fileInput = $('#file-input');

  $('#btn-add-files').addEventListener('click', () => fileInput.click());
  $('#btn-browse').addEventListener('click', openBrowser);
  dropzone.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) uploadFiles(fileInput.files);
    fileInput.value = '';
  });

  // Arrastrar y soltar sobre todo el panel, no solo sobre el recuadro.
  const panel = $('#library-panel');
  for (const type of ['dragenter', 'dragover']) {
    panel.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add('drag');
    });
  }
  for (const type of ['dragleave', 'drop']) {
    panel.addEventListener(type, (event) => {
      event.preventDefault();
      if (type === 'dragleave' && panel.contains(event.relatedTarget)) return;
      dropzone.classList.remove('drag');
    });
  }
  panel.addEventListener('drop', (event) => {
    const files = event.dataTransfer?.files;
    if (files && files.length) uploadFiles(files);
  });
}

async function uploadFiles(files) {
  if (!state.project) return;
  const note = toast(`Subiendo ${files.length} archivo(s)…`, '', 60000);
  try {
    const result = await api.upload(state.project.id, files);
    note.remove();
    for (const error of result.errors || []) toastError(error);
    if (result.added?.length) {
      toast(`${result.added.length} archivo(s) añadidos`, 'ok');
      actions.onProjectChanged(result.project);
      actions.watchAnalysis();
    }
  } catch (error) {
    note.remove();
    toastError(error);
  }
}

// ── Explorador del disco ────────────────────────────────────

async function openBrowser(startPath = '') {
  const container = openModal('Añadir material del disco', el('p', { class: 'hint' }, 'Cargando…'));
  await renderBrowser(container, startPath);
}

async function renderBrowser(container, path) {
  let data;
  try {
    data = await api.browse(path);
  } catch (error) {
    toastError(error);
    return;
  }
  clear(container);
  const selected = new Set();

  container.appendChild(el('div', { class: 'crumb' }, data.path));
  const rows = el('div', { style: { maxHeight: '46vh', overflowY: 'auto', margin: '0 -6px' } });

  if (data.parent) {
    rows.appendChild(el('div', {
      class: 'list-row',
      style: { cursor: 'pointer' },
      onclick: () => renderBrowser(container, data.parent),
    }, [el('span', {}, '📁'), el('span', { class: 'grow name' }, '..')]));
  }

  for (const entry of data.entries) {
    const row = el('div', { class: 'list-row', style: { cursor: 'pointer' } }, [
      el('span', {}, entry.is_dir ? '📁' : '🎞️'),
      el('div', { class: 'grow' }, [
        el('div', { class: 'name' }, entry.name),
        entry.is_dir ? null : el('div', { class: 'sub' }, fmtSize(entry.size)),
      ]),
    ]);
    if (entry.is_dir) {
      const addFolder = el('button', { class: 'ghost small' }, 'Añadir carpeta');
      addFolder.addEventListener('click', (event) => {
        event.stopPropagation();
        importPaths([entry.path]);
      });
      row.appendChild(addFolder);
      row.addEventListener('click', () => renderBrowser(container, entry.path));
    } else {
      row.addEventListener('click', () => {
        if (selected.has(entry.path)) { selected.delete(entry.path); row.classList.remove('active'); }
        else { selected.add(entry.path); row.classList.add('active'); }
        countLabel.textContent = selected.size ? `Añadir ${selected.size}` : 'Añadir seleccionados';
      });
    }
    rows.appendChild(row);
  }
  container.appendChild(rows);

  const countLabel = el('button', { class: 'primary' }, 'Añadir seleccionados');
  countLabel.addEventListener('click', () => {
    if (!selected.size) { toast('No has seleccionado nada'); return; }
    importPaths([...selected]);
  });
  container.appendChild(el('div', { class: 'btn-row', style: { justifyContent: 'flex-end' } }, [
    el('button', { class: 'ghost', onclick: () => importPaths([data.path]) }, 'Añadir esta carpeta entera'),
    countLabel,
  ]));
}

async function importPaths(paths) {
  closeModal();
  const note = toast('Importando…', '', 60000);
  try {
    const result = await api.importPaths(state.project.id, paths);
    note.remove();
    for (const error of result.errors || []) toastError(error);
    if (result.added?.length) {
      toast(`${result.added.length} archivo(s) añadidos`, 'ok');
      actions.onProjectChanged(result.project);
      actions.watchAnalysis();
    } else if (!result.errors?.length) {
      toast('No se ha encontrado material compatible ahí');
    }
  } catch (error) {
    note.remove();
    toastError(error);
  }
}

// ── Listado ─────────────────────────────────────────────────

export function renderLibrary() {
  const container = clear($('#library-groups'));
  const dropzone = $('#dropzone');
  if (!state.project) return;

  const assets = state.project.assets;
  dropzone.classList.toggle('compact', assets.length > 0);
  if (!assets.length) return;

  const music = musicAsset();
  const groups = [
    ['Vídeos', assets.filter((a) => a.kind === 'video')],
    ['Fotos', assets.filter((a) => a.kind === 'image')],
    ['Audio', assets.filter((a) => a.kind === 'audio')],
  ];

  for (const [title, items] of groups) {
    if (!items.length) continue;
    container.appendChild(el('div', { class: 'group-title' }, [
      el('span', {}, title),
      el('span', {}, String(items.length)),
    ]));
    for (const item of items) container.appendChild(assetRow(item, music));
  }
}

function assetRow(item, music) {
  const missing = (state.project.missing_files || []).includes(item.id);
  const analyzing = !item.analysis.analyzed;
  const isMusic = music && music.id === item.id;

  const thumb = el('div', { class: 'asset-thumb' });
  if (item.kind === 'audio') {
    thumb.appendChild(el('span', {}, '🎵'));
  } else if (item.analysis.analyzed || item.thumbnail) {
    thumb.appendChild(el('img', {
      src: `/api/projects/${state.project.id}/assets/${item.id}/thumb`,
      loading: 'lazy',
      onerror: (event) => { event.target.replaceWith(el('span', {}, KIND_ICON[item.kind])); },
    }));
  } else {
    thumb.appendChild(el('span', {}, KIND_ICON[item.kind]));
  }
  if (analyzing) thumb.appendChild(el('div', { class: 'badge-analyzing' }, '···'));

  const meta = [];
  if (item.duration > 0) meta.push(fmtDuration(item.duration));
  if (item.width) meta.push(`${item.width}×${item.height}`);
  if (missing) meta.push('⚠ no encontrado');
  else if (isMusic) meta.push('música');

  const row = el('div', {
    class: `asset${item.enabled ? '' : ' disabled'}${isMusic ? ' music-active' : ''}`,
    draggable: 'true',
    title: item.path,
  }, [
    thumb,
    el('div', { class: 'asset-body' }, [
      el('div', { class: 'asset-name' }, item.name),
      el('div', { class: 'asset-meta' }, meta.map((text) => el('span', {}, text))),
    ]),
    el('div', { class: 'asset-actions' }, assetActions(item, isMusic)),
  ]);

  row.addEventListener('dragstart', (event) => {
    event.dataTransfer.setData('text/autoedit-asset', item.id);
    event.dataTransfer.effectAllowed = 'copy';
  });
  row.addEventListener('dblclick', () => {
    if (item.kind === 'audio') actions.setMusic(isMusic ? null : item.id);
    else actions.addClip(item.id);
  });
  return row;
}

function assetActions(item, isMusic) {
  const buttons = [];
  if (item.kind === 'audio') {
    buttons.push(el('button', {
      class: 'icon-btn',
      title: isMusic ? 'Quitar como música' : 'Usar como música',
      onclick: (event) => { event.stopPropagation(); actions.setMusic(isMusic ? null : item.id); },
    }, isMusic ? '✓' : '♫'));
  } else {
    buttons.push(el('button', {
      class: 'icon-btn',
      title: 'Añadir al final del montaje',
      onclick: (event) => { event.stopPropagation(); actions.addClip(item.id); },
    }, '+'));
  }
  buttons.push(el('button', {
    class: 'icon-btn',
    title: item.enabled ? 'Excluir del auto-montaje' : 'Incluir en el auto-montaje',
    onclick: async (event) => {
      event.stopPropagation();
      try {
        actions.onProjectChanged(await api.patchAsset(state.project.id, item.id, { enabled: !item.enabled }));
      } catch (error) { toastError(error); }
    },
  }, item.enabled ? '👁' : '🚫'));
  buttons.push(el('button', {
    class: 'icon-btn',
    title: 'Quitar del proyecto',
    onclick: async (event) => {
      event.stopPropagation();
      const ok = await confirmDialog(
        'Quitar del proyecto',
        `«${item.name}» se quitará del proyecto y de la línea de tiempo. El archivo original no se borra.`,
        'Quitar',
      );
      if (!ok) return;
      try {
        actions.onProjectChanged(await api.deleteAsset(state.project.id, item.id));
      } catch (error) { toastError(error); }
    },
  }, '✕'));
  return buttons;
}

/** Vigila el trabajo de análisis y refresca el panel cuando termina. */
export async function watchAnalysisJob(jobId, onTick) {
  try {
    await followJob(jobId, onTick);
  } catch (error) {
    if (String(error.message) !== 'Cancelado') toastError(error);
  }
}
