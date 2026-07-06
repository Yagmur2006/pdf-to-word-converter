/**
 * theme.js
 * ---------------------------------------------------------------
 * Light/dark theme toggle. The actual attribute is applied
 * synchronously in an inline <script> in <head> (before first
 * paint, to avoid a flash of the wrong theme) — this module only
 * wires up the toggle button and persists the user's choice.
 * ---------------------------------------------------------------
 */

const STORAGE_KEY = 'docuswift-theme';

export function initThemeToggle() {
  const toggle = document.getElementById('themeToggle');
  if (!toggle) return;

  toggle.addEventListener('click', () => {
    const root = document.documentElement;
    const current = root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem(STORAGE_KEY, next);
  });
}
