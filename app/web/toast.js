(function () {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const style = document.createElement("style");
  style.textContent =
    ".toast{opacity:0;transform:translateY(1rem)}.toast.show{opacity:1;transform:translateY(0)}";
  document.head.appendChild(style);

  function show(message, type, duration) {
    const el = document.createElement("div");
    el.className =
      "toast flex items-center gap-2 rounded-lg border px-4 py-3 text-sm font-medium shadow-sm transition-all duration-200 " +
      type;
    el.onclick = () => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 200);
    };
    el.textContent = message;
    container.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    if (duration > 0) {
      setTimeout(() => {
        el.classList.remove("show");
        setTimeout(() => el.remove(), 200);
      }, duration);
    }
  }

  window.toast = {
    success: (msg) => show(msg, "ui-toast-success", 2500),
    error: (msg) => show(msg, "ui-toast-error", 0),
    info: (msg) => show(msg, "ui-toast-info", 2500),
    show: show,
  };
})();
