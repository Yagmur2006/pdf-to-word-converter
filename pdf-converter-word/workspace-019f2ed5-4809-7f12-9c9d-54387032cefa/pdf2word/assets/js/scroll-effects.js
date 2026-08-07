/**
 * scroll-effects.js
 * ---------------------------------------------------------------
 * Two small, dependency-free scroll-driven enhancements:
 *   1. Reveal-on-scroll for elements marked with `.reveal`.
 *   2. A subtle drop shadow on the sticky navbar once the page
 *      has scrolled past the top.
 *   3. Animated count-up for the stats section.
 * All use IntersectionObserver, so there is no scroll-event
 * polling / jank.
 * ---------------------------------------------------------------
 */

export function initScrollReveal() {
  const targets = document.querySelectorAll('.reveal');
  if (!targets.length) return;

  if (!('IntersectionObserver' in window)) {
    targets.forEach((el) => el.classList.add('is-visible'));
    return;
  }

  const observer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          obs.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
  );

  targets.forEach((el) => observer.observe(el));
}

export function initNavbarScrollShadow() {
  const navbar = document.getElementById('navbar');
  if (!navbar) return;

  const update = () => {
    navbar.classList.toggle('is-scrolled', window.scrollY > 8);
  };

  update();
  window.addEventListener('scroll', update, { passive: true });
}

/** Animates each [data-count] element from 0 to its target value once visible. */
export function initCounters() {
  const counters = document.querySelectorAll('[data-count]');
  if (!counters.length) return;

  const animate = (el) => {
    const target = Number(el.dataset.count);
    const suffix = el.dataset.suffix || '';
    const duration = 1400;
    const start = performance.now();

    const formatValue = (value) => {
      if (target >= 1000) {
        return Math.round(value).toLocaleString('en-US');
      }
      return Math.round(value).toString();
    };

    function step(now) {
      const progress = Math.min((now - start) / duration, 1);
      // Ease-out cubic for a natural deceleration toward the final value.
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = formatValue(target * eased) + suffix;
      if (progress < 1) {
        requestAnimationFrame(step);
      }
    }
    requestAnimationFrame(step);
  };

  if (!('IntersectionObserver' in window)) {
    counters.forEach(animate);
    return;
  }

  const observer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          animate(entry.target);
          obs.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.5 }
  );

  counters.forEach((el) => observer.observe(el));
}
