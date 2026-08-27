// Diálogos de exportación y de gestión de proyectos.

import { api, followJob } from './api.js';
import { fmtDuration, fmtSize, state, totalDuration } from './state.js';
import {
  $, append, checkbox, clear, closeModal, confirmDialog, el, openModal, toast, toastError,
} from './ui.js';

let actions = {};

export function initDialogs(hooks) {
  actions = hooks;
}

// ── Exportar ────────────────────────────────────────────────

const HELP = {
  mp4: 'Renderiza el vídeo definitivo con todos los efectos, el color y la mezcla de audio.',
  capcut: 'Crea un borrador de CapCut con tus clips ya ordenados y recortados, listo para seguir editando allí.',
  fcpxml: 'El camino más fiable hacia un editor de escritorio: DaVinci Resolve, Premiere Pro o Final Cut.',
  edl: 'Lista de cortes clásica. La lee casi cualquier programa, pero solo lleva tiempos.',
  project: 'Copia completa del proyecto de AutoEdit, con efectos, color y análisis.',
  shotlist: 'Un resumen en Markdown del montaje, para revisarlo o compartirlo.',
};

export function openExportDialog() {
  if (!state.project) return;
  let format = 'mp4';
  let install = true;
  let asZip = false;

  const container = openModal('Exportar');
  const grid = el('div', { class: 'format-grid' });
  const options = el('div', {});
  const status = el('div', {});

  const formats = state.health?.formats || [];
  const cards = new Map();
  for (const item of formats) {
    const card = el('button', { class: `format-card${item.id === format ? ' active' : ''}` }, [
      el('h4', {}, [el('span', {}, item.emoji), el('span', {}, item.name)]),
      el('p', {}, item.description),
    ]);
    card.addEventListener('click', () => {
      format = item.id;
      for (const [id, node] of cards) node.classList.toggle('active', id === format);
      renderOptions();
    });
    cards.set(item.id, card);
    grid.appendChild(card);
  }

  function renderOptions() {
    clear(options);
    options.appendChild(el('div', { class: 'note ok' }, HELP[format] || ''));

    if (format === 'capcut') {
      const drafts = state.health?.capcut_drafts;
      options.appendChild(checkbox(
        drafts
          ? `Copiarlo directamente a la carpeta de CapCut (${drafts})`
          : 'Copiarlo a la carpeta de CapCut (no se ha encontrado en este equipo)',
        install && !!drafts,
        (e) => { install = e.target.checked; },
      ));
      options.appendChild(checkbox('Empaquetar en un .zip en vez de una carpeta', asZip,
        (e) => { asZip = e.target.checked; }));
      options.appendChild(el('div', { class: 'note' },
        'El formato de borrador de CapCut no es oficial. AutoEdit conserva los cortes, '
        + 'los recortes, la música y los textos; las transiciones y los filtros quedan '
        + 'anotados en el archivo AUTOEDIT.md para reponerlos en dos clics. '
        + 'El borrador apunta a tus archivos originales: no los muevas después.'));
    }
    if (format === 'mp4') {
      options.appendChild(el('div', { class: 'note' },
        `Se renderizarán ${fmtDuration(totalDuration())} a `
        + `${state.project.timeline.width}×${state.project.timeline.height}. `
        + 'Los clips que no hayan cambiado se reutilizan de la caché.'));
    }
    if (format === 'fcpxml' || format === 'edl') {
      options.appendChild(el('div', { class: 'note' },
        'Los efectos de movimiento y la corrección de color no viajan en este formato: '
        + 'lo que llega son los cortes, los recortes y la sincronía.'));
    }
  }

  const runButton = el('button', { class: 'primary' }, 'Exportar');
  runButton.addEventListener('click', () => runExport());

  async function runExport() {
    runButton.disabled = true;
    clear(status);
    const label = el('div', { class: 'hint' }, 'Preparando…');
    status.appendChild(label);
    try {
      const request = format === 'mp4'
        ? api.render(state.project.id, false)
        : api.export(state.project.id, { format, install, zip: asZip });
      const { job_id: jobId } = await request;
      const result = await followJob(jobId, (job) => {
        label.textContent = `${job.message} · ${Math.round(job.progress * 100)}%`;
        actions.onJobTick(job);
      });
      clear(status);
      append(status, resultBlock(format, result));
      actions.onExportDone();
    } catch (error) {
      clear(status);
      status.appendChild(el('div', { class: 'note' }, String(error.message || error)));
      toastError(error);
    } finally {
      runButton.disabled = false;
    }
  }

  renderOptions();
  append(container, [
    grid,
    options,
    el('div', { class: 'btn-row', style: { justifyContent: 'flex-end' } }, [
      el('button', { class: 'ghost', onclick: closeModal }, 'Cerrar'),
      runButton,
    ]),
    status,
  ]);
}

function resultBlock(format, result) {
  const nodes = [el('div', { class: 'note ok' }, '✓ Exportación terminada')];

  if (format === 'mp4' && result?.path) {
    nodes.push(el('div', { class: 'crumb' }, result.path));
    nodes.push(el('div', { class: 'btn-row' }, [
      el('a', {
        class: 'primary', style: { textDecoration: 'none' },
        href: `/api/projects/${state.project.id}/file?path=${encodeURIComponent(result.path)}&download=true`,
      }, 'Descargar el vídeo'),
    ]));
    for (const warning of result.warnings || []) nodes.push(el('div', { class: 'note' }, warning));
  } else if (format === 'capcut') {
    nodes.push(el('div', { class: 'crumb' }, result.installed_to || result.folder));
    if (result.installed_to) {
      nodes.push(el('div', { class: 'note ok' },
        'Copiado a la carpeta de borradores. Abre CapCut y lo verás en la lista.'));
    } else {
      nodes.push(el('div', { class: 'note' },
        'Copia esa carpeta dentro de la carpeta de borradores de CapCut. '
        + 'Las instrucciones exactas están en AUTOEDIT.md, dentro de la carpeta.'));
    }
    if (result.zip) {
      nodes.push(el('div', { class: 'btn-row' }, [
        el('a', {
          class: 'primary', style: { textDecoration: 'none' },
          href: `/api/projects/${state.project.id}/file?path=${encodeURIComponent(result.zip)}&download=true`,
        }, 'Descargar el .zip'),
      ]));
    }
    for (const note of result.notes || []) nodes.push(el('div', { class: 'note' }, note));
    if (result.missing?.length) {
      nodes.push(el('div', { class: 'note' },
        `⚠ Estos archivos no están en su sitio: ${result.missing.join(', ')}`));
    }
  } else if (result?.path) {
    nodes.push(el('div', { class: 'crumb' }, result.path));
    nodes.push(el('div', { class: 'btn-row' }, [
      el('a', {
        class: 'primary', style: { textDecoration: 'none' },
        href: `/api/projects/${state.project.id}/file?path=${encodeURIComponent(result.path)}&download=true`,
      }, 'Descargar'),
    ]));
    for (const note of result.notes || []) nodes.push(el('div', { class: 'note' }, note));
  }
  return nodes;
}

// ── Proyectos ───────────────────────────────────────────────

export async function openProjectsDialog() {
  const container = openModal('Proyectos', el('p', { class: 'hint' }, 'Cargando…'));
  let projects = [];
  try {
    projects = (await api.projects()).projects;
  } catch (error) {
    toastError(error);
    return;
  }
  clear(container);

  // Crear va arriba del todo: es lo que la gente viene a buscar aquí.
  const nameInput = el('input', {
    type: 'text', placeholder: 'Nombre del proyecto nuevo…',
  });
  const createButton = el('button', { class: 'primary' }, '+ Crear proyecto');
  const create = () => { closeModal(); actions.createProject(nameInput.value); };
  createButton.addEventListener('click', create);
  nameInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') create(); });

  const list = el('div', { style: { maxHeight: '46vh', overflowY: 'auto', margin: '0 -6px' } });
  for (const item of projects) {
    const esActual = state.project && item.id === state.project.id;
    const row = el('div', {
      class: `list-row${esActual ? ' active' : ''}`,
      style: { cursor: 'pointer' },
      onclick: () => { closeModal(); actions.openProject(item.id); },
    }, [
      el('span', {}, '🎬'),
      el('div', { class: 'grow' }, [
        el('div', { class: 'name' }, item.name + (esActual ? '  ·  abierto' : '')),
        el('div', { class: 'sub' },
          `${item.assets} archivos · ${item.clips} clips`
          + `${item.style ? ` · ${item.style}` : ''} · ${relative(item.updated_at)}`),
      ]),
      el('div', { class: 'row-actions' }, [
        el('button', {
          class: 'icon-btn trash',
          title: 'Borrar este proyecto',
          onclick: (event) => { event.stopPropagation(); borrarProyecto(item); },
        }, '🗑'),
      ]),
    ]);
    list.appendChild(row);
  }
  if (!projects.length) {
    list.appendChild(el('div', { class: 'hint', style: { padding: '18px', textAlign: 'center' } },
      'Todavía no hay proyectos.'));
  }

  append(container, [
    el('div', { class: 'new-project' }, [nameInput, createButton]),
    list,
  ]);
  nameInput.focus();
}

/** Borra un proyecto. Aquí sí se pregunta: se van archivos del disco. */
async function borrarProyecto(item) {
  const ok = await confirmDialog(
    'Borrar proyecto',
    `Se borrará «${item.name}» con su caché de render y sus exportaciones, que pueden `
    + 'ocupar bastante. Esto no tiene vuelta atrás. Tus vídeos y fotos originales no se tocan.',
    'Borrar',
  );
  if (!ok) { openProjectsDialog(); return; }

  const eraElActual = state.project && item.id === state.project.id;
  try {
    await api.deleteProject(item.id);
    toast(`«${item.name}» borrado`, 'ok');
    if (eraElActual) {
      const { projects } = await api.projects();
      closeModal();
      if (projects.length) await actions.openProject(projects[0].id);
      else await actions.createProject('');
      return;
    }
  } catch (error) {
    toastError(error);
  }
  openProjectsDialog();
}

function relative(timestamp) {
  if (!timestamp) return 'sin fecha';
  const seconds = Date.now() / 1000 - timestamp;
  if (seconds < 90) return 'hace un momento';
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `hace ${Math.round(seconds / 3600)} h`;
  return new Date(timestamp * 1000).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
}
