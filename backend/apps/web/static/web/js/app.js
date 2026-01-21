(() => {
  // Bootstrap tooltips (opt-in)
  try {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach((el) => {
      // eslint-disable-next-line no-undef
      new bootstrap.Tooltip(el);
    });
  } catch (_) {
    // no-op
  }

  // Auto-dismiss alerts (messages) after a short delay
  const alerts = document.querySelectorAll('.app-alert[data-autodismiss="true"]');
  alerts.forEach((alertEl) => {
    const timeoutMs = 5200;
    window.setTimeout(() => {
      if (!alertEl.isConnected) return;
      try {
        // eslint-disable-next-line no-undef
        const inst = bootstrap.Alert.getOrCreateInstance(alertEl);
        inst.close();
      } catch (_) {
        alertEl.remove();
      }
    }, timeoutMs);
  });

  // Materials filter (flow materials page)
  const filterInput = document.querySelector('[data-material-filter]');
  const picker = document.querySelector('[data-material-picker]');
  if (filterInput && picker) {
    const items = Array.from(picker.querySelectorAll('li'));
    const normalize = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
    filterInput.addEventListener('input', () => {
      const q = normalize(filterInput.value);
      items.forEach((li) => {
        const t = normalize(li.innerText);
        li.style.display = !q || t.includes(q) ? '' : 'none';
      });
    });
  }

  // Loading state for forms (auth, plan pay, etc.)
  document.querySelectorAll('form.auth-form, form.plan-form').forEach((form) => {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('button[type="submit"]');
      if (btn && !btn.classList.contains('is-loading')) {
        btn.classList.add('is-loading');
        // Prevent double submit
        setTimeout(() => {
          btn.disabled = true;
        }, 10);
      }
    });
  });

  // Add animate-in class to cards on page load (staggered)
  const animateCards = document.querySelectorAll('.card:not(.animate-in):not([class*="animate-in-delay"])');
  animateCards.forEach((card, index) => {
    if (index < 8) {
      card.style.animationDelay = `${index * 50}ms`;
      card.classList.add('animate-in');
    }
  });
})();

