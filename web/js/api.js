// Cliente HTTP y seguimiento de trabajos en segundo plano.

async function request(method, url, body, options = {}) {
  const init = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (data && data.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch { /* la respuesta no era JSON */ }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body),
  patch: (url, body) => request('PATCH', url, body),
  del: (url) => request('DELETE', url),

  health: () => request('GET', '/api/health'),
  styles: () => request('GET', '/api/styles'),
  fonts: () => request('GET', '/api/fonts'),
  browse: (path) => request('GET', `/api/browse?path=${encodeURIComponent(path || '')}`),

  projects: () => request('GET', '/api/projects'),
  createProject: (name) => request('POST', '/api/projects', { name }),
  project: (id) => request('GET', `/api/projects/${id}`),
  patchProject: (id, body) => request('PATCH', `/api/projects/${id}`, body),
  deleteProject: (id) => request('DELETE', `/api/projects/${id}`),
  duplicateProject: (id) => request('POST', `/api/projects/${id}/duplicate`),

  importPaths: (id, paths) => request('POST', `/api/projects/${id}/assets/path`, { paths }),
  upload: (id, files) => {
    const form = new FormData();
    for (const file of files) form.append('files', file);
    return request('POST', `/api/projects/${id}/assets/upload`, form);
  },
  deleteAsset: (id, assetId) => request('DELETE', `/api/projects/${id}/assets/${assetId}`),
  patchAsset: (id, assetId, body) => request('PATCH', `/api/projects/${id}/assets/${assetId}`, body),
  analyze: (id, force) => request('POST', `/api/projects/${id}/analyze?force=${force ? 'true' : 'false'}`),

  interpret: (id, body) => request('POST', `/api/projects/${id}/interpret`, body),
  autoedit: (id, body) => request('POST', `/api/projects/${id}/autoedit`, body),
  reshuffle: (id) => request('POST', `/api/projects/${id}/reshuffle`),

  addClip: (id, body) => request('POST', `/api/projects/${id}/clips`, body),
  patchClip: (id, clipId, changes) => request('PATCH', `/api/projects/${id}/clips/${clipId}`, { changes }),
  moveClip: (id, clipId, index) => request('POST', `/api/projects/${id}/clips/${clipId}/move`, { index }),
  splitClip: (id, clipId, at) => request('POST', `/api/projects/${id}/clips/${clipId}/split`, { at }),
  duplicateClip: (id, clipId) => request('POST', `/api/projects/${id}/clips/${clipId}/duplicate`),
  deleteClip: (id, clipId) => request('DELETE', `/api/projects/${id}/clips/${clipId}`),
  applyAll: (id, changes) => request('POST', `/api/projects/${id}/clips/apply-all`, { changes }),

  addText: (id, body) => request('POST', `/api/projects/${id}/texts`, body),
  patchText: (id, textId, changes) => request('PATCH', `/api/projects/${id}/texts/${textId}`, { changes }),
  deleteText: (id, textId) => request('DELETE', `/api/projects/${id}/texts/${textId}`),

  setMusic: (id, assetId) => request('POST', `/api/projects/${id}/music`, { asset_id: assetId }),

  addTrack: (id, name) => request('POST', `/api/projects/${id}/tracks`, { name }),
  patchTrack: (id, trackId, changes) => request('PATCH', `/api/projects/${id}/tracks/${trackId}`, { changes }),
  deleteTrack: (id, trackId) => request('DELETE', `/api/projects/${id}/tracks/${trackId}`),
  addTrackClip: (id, trackId, assetId, start) =>
    request('POST', `/api/projects/${id}/tracks/${trackId}/clips`, { asset_id: assetId, start }),

  render: (id, preview) => request('POST', `/api/projects/${id}/render`, { preview }),
  export: (id, body) => request('POST', `/api/projects/${id}/export`, body),
  exports: (id) => request('GET', `/api/projects/${id}/exports`),

  job: (jobId) => request('GET', `/api/jobs/${jobId}`),
  cancelJob: (jobId) => request('POST', `/api/jobs/${jobId}/cancel`),
};

/**
 * Sigue un trabajo hasta que termina. `onTick` recibe el estado en cada sondeo.
 * Devuelve el resultado, o lanza si el trabajo falló.
 */
export async function followJob(jobId, onTick) {
  let delay = 260;
  for (;;) {
    const job = await api.job(jobId);
    if (onTick) onTick(job);
    if (job.status === 'done') return job.result;
    if (job.status === 'error') throw new Error(job.error || job.message);
    if (job.status === 'cancelled') throw new Error('Cancelado');
    await new Promise((resolve) => setTimeout(resolve, delay));
    // Sondeo progresivamente más espaciado: los renders largos no necesitan
    // que preguntemos cuatro veces por segundo.
    delay = Math.min(delay * 1.15, 1400);
  }
}
