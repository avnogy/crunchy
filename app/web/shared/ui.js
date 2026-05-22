(function () {
  function query(selector, root = document) {
    return root.querySelector(selector);
  }

  function queryAll(selector, root = document) {
    return Array.from(root.querySelectorAll(selector));
  }

  function jsonHeaders(headers) {
    return { "Content-Type": "application/json", ...(headers || {}) };
  }

  async function parseJson(response) {
    try {
      return await response.json();
    } catch (error) {
      return null;
    }
  }

  async function request(url, options = {}) {
    const response = await fetch(url, options);
    const data = await parseJson(response);

    if (!response.ok) {
      const error = new Error(data?.detail || `HTTP ${response.status}`);
      error.response = response;
      error.data = data;
      throw error;
    }

    return data;
  }

  async function requestJson(url, options = {}) {
    const { body, headers, ...rest } = options;
    return request(url, {
      ...rest,
      headers: jsonHeaders(headers),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  function setBusyState(element, isBusy, busyLabel) {
    if (!element) {
      return;
    }

    if (!element.dataset.originalLabel) {
      element.dataset.originalLabel = element.textContent || "";
    }

    element.disabled = Boolean(isBusy);
    if (busyLabel) {
      element.textContent = isBusy ? busyLabel : element.dataset.originalLabel;
    }
  }

  async function withBusyState(element, busyLabel, action) {
    setBusyState(element, true, busyLabel);
    try {
      return await action();
    } finally {
      setBusyState(element, false, busyLabel);
    }
  }

  function startPolling(callback, intervalMs) {
    let timer = null;

    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const start = () => {
      stop();
      callback();
      timer = setInterval(callback, intervalMs);
    };

    return { start, stop };
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderEmptyState(message) {
    return `
      <div class="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center text-sm text-slate-500">
        ${escapeHtml(message)}
      </div>
    `;
  }

  function toggleClasses(element, shouldApply, enabledClasses, disabledClasses = []) {
    if (!element) {
      return;
    }

    enabledClasses.forEach((className) => {
      element.classList.toggle(className, shouldApply);
    });
    disabledClasses.forEach((className) => {
      element.classList.toggle(className, !shouldApply);
    });
  }

  window.ui = {
    query,
    queryAll,
    request,
    requestJson,
    setBusyState,
    withBusyState,
    startPolling,
    escapeHtml,
    renderEmptyState,
    toggleClasses,
  };
})();
