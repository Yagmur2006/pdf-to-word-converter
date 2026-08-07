/**
 * ui.js
 * ---------------------------------------------------------------
 * Small, dependency-free DOM helpers: state switching for the
 * upload card, human-readable file sizes, and the mobile nav toggle.
 * Keeping DOM manipulation isolated here means main.js only deals
 * with orchestration/business logic.
 * ---------------------------------------------------------------
 */

const states = ['stateIdle', 'stateProgress', 'stateDone', 'stateError'];

/** Shows exactly one of the four upload-card states, hides the rest. */
export function showState(stateId) {
  for (const id of states) {
    const el = document.getElementById(id);
    if (el) el.hidden = id !== stateId;
  }
}

/** Formats bytes into a friendly "12.3 MB" style string. */
export function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

/** Updates the progress bar fill, ARIA value and status message text. */
export function setProgress(percent, message) {
  const fill = document.getElementById('progressFill');
  const bar = document.getElementById('progressBar');
  const msg = document.getElementById('progressMessage');

  if (fill) fill.style.width = `${percent}%`;
  if (bar) bar.setAttribute('aria-valuenow', String(percent));
  if (msg && message) msg.textContent = message;
}

/** Wires up the hamburger menu toggle for small screens. */
export function initMobileNav() {
  const toggle = document.getElementById('navToggle');
  const menu = document.getElementById('mobileMenu');
  if (!toggle || !menu) return;

  toggle.addEventListener('click', () => {
    const isOpen = !menu.hidden;
    menu.hidden = isOpen;
    toggle.setAttribute('aria-expanded', String(!isOpen));
    toggle.classList.toggle('is-active', !isOpen);
  });

  // Close the mobile menu after a nav link is tapped.
  menu.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => {
      menu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
    });
  });
}
