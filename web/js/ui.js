// Utilidades de interfaz: creación de nodos, avisos y diálogos.

/**
 * Crea un elemento. `props` admite atributos, `class`, `style`, `dataset`,
 * manejadores `onclick`… y `children` puede ser texto, nodos o listas.
 */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function $(selector) {
  return document.querySelector(selector);
}

// ── Avisos ──────────────────────────────────────────────────

export function toast(message, kind = '', ms = 4200) {
  const node = el('div', { class: `toast ${kind}` }, message);
  $('#toasts').appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity .25s, transform .25s';
    node.style.opacity = '0';
    node.style.transform = 'translateX(16px)';
    setTimeout(() => node.remove(), 260);
  }, ms);
  return node;
}

export function toastError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return toast(message, 'error', 7000);
}

// ── Diálogos ────────────────────────────────────────────────

let onCloseModal = null;

export function openModal(title, body, onClose = null) {
  $('#modal-title').textContent = title;
  const container = clear($('#modal-body'));
  append(container, body);
  $('#modal-backdrop').hidden = false;
  onCloseModal = onClose;
  return container;
}

export function closeModal() {
  $('#modal-backdrop').hidden = true;
  clear($('#modal-body'));
  if (onCloseModal) { const fn = onCloseModal; onCloseModal = null; fn(); }
}

export function initModal() {
  $('#modal-close').addEventListener('click', closeModal);
  $('#modal-backdrop').addEventListener('click', (event) => {
    if (event.target.id === 'modal-backdrop') closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('#modal-backdrop').hidden) closeModal();
  });
}

export function confirmDialog(title, message, confirmLabel = 'Continuar') {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => { if (!settled) { settled = true; resolve(value); } };
    openModal(title, [
      el('p', { style: { margin: '0 0 16px', color: 'var(--text-dim)' } }, message),
      el('div', { class: 'btn-row', style: { justifyContent: 'flex-end' } }, [
        el('button', { class: 'ghost', onclick: () => { finish(false); closeModal(); } }, 'Cancelar'),
        el('button', { class: 'primary', onclick: () => { finish(true); closeModal(); } }, confirmLabel),
      ]),
    ], () => finish(false));
  });
}

// ── Controles de formulario ─────────────────────────────────

export function field(label, control, valueLabel = null) {
  return el('div', { class: 'field' }, [
    el('label', {}, [el('span', {}, label), valueLabel ? el('b', {}, valueLabel) : null]),
    control,
  ]);
}

export function slider({ min, max, step, value, oninput, onchange }) {
  return el('input', {
    type: 'range', min, max, step, value,
    oninput: oninput || null,
    onchange: onchange || null,
  });
}

export function select(options, value, onchange) {
  const node = el('select', { onchange });
  for (const option of options) {
    const [optionValue, label] = Array.isArray(option) ? option : [option, option];
    node.appendChild(el('option', { value: optionValue, selected: optionValue === value }, label));
  }
  return node;
}

export function checkbox(label, checked, onchange) {
  return el('label', { class: 'toggle' }, [
    el('input', { type: 'checkbox', checked: !!checked, onchange }),
    el('span', {}, label),
  ]);
}

export function numberInput(value, { min, max, step = 0.1, onchange }) {
  return el('input', { type: 'number', value, min, max, step, onchange });
}

/** Evita disparar una petición por cada pulsación de tecla. */
export function debounce(fn, ms = 300) {
  let handle = null;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), ms);
  };
}
