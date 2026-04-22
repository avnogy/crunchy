(function() {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const style = document.createElement('style');
  style.textContent = '.toast{opacity:0;transform:translateY(1rem)}.toast.show{opacity:1;transform:translateY(0)}';
  document.head.appendChild(style);

  function show(message, type, duration) {
    const el = document.createElement('div');
    el.className = 'toast flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium text-white shadow-sm transition-all duration-200 ' + type;
    el.textContent = message;
    container.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    if (duration > 0) {
      setTimeout(() => {
        el.classList.remove('show');
        setTimeout(() => el.remove(), 200);
      }, duration);
    }
  }

  window.toast = {
    success: (msg) => show(msg, 'bg-green-500', 2500),
    error: (msg) => show(msg, 'bg-red-500', 0),
    info: (msg) => show(msg, 'bg-blue-500', 2500),
    show: show,
  };
})();