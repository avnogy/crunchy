const expandedJobs = new Set();
const requestedJobId = new URLSearchParams(window.location.search).get("job");
const pollIntervalMs = Math.max(500, Number(window.jobsPollIntervalMs) || 3000);
let pollInterval = null;

if (requestedJobId) {
  expandedJobs.add(requestedJobId);
}

function formatDuration(totalSeconds) {
  const safeSeconds = Math.max(0, Number(totalSeconds) || 0);
  const hours = Math.floor(safeSeconds / 3600);
  const mins = Math.floor((safeSeconds % 3600) / 60);
  const secs = Math.round(safeSeconds % 60);
  if (hours > 0) {
    return `${hours.toString().padStart(2, "0")}:${mins
      .toString()
      .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function parseCurrentTime(value) {
  const parts = String(value || "").split(":");
  if (parts.length === 3) {
    return (
      Number.parseInt(parts[0], 10) * 3600 +
      Number.parseInt(parts[1], 10) * 60 +
      Number.parseFloat(parts[2])
    );
  }

  if (parts.length === 2) {
    return Number.parseInt(parts[0], 10) * 60 + Number.parseFloat(parts[1]);
  }

  return Number.NaN;
}

function getEta(job) {
  if (!job.progress?.current || !job.progress?.duration || !job.speed) {
    return "-";
  }

  const currentSecs = parseCurrentTime(job.progress.current);
  const speed = Number.parseFloat(job.speed);
  if (!Number.isFinite(currentSecs) || currentSecs <= 0 || speed <= 0) {
    return "-";
  }

  const etaMinutes = Math.round(
    (job.progress.duration - currentSecs) / speed / 60,
  );
  return etaMinutes > 0 ? `${etaMinutes}m` : "-";
}

function formatCurrentTime(value) {
  const totalSeconds = parseCurrentTime(value);
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "-";
  }
  return formatDuration(totalSeconds);
}

function getStateClasses(state) {
  const stateColors = {
    completed: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    running: "bg-blue-100 text-blue-800",
    queued: "bg-yellow-100 text-yellow-800",
    cancelled: "bg-gray-100 text-gray-600",
  };
  return stateColors[state] || "bg-gray-100 text-gray-600";
}

function renderIcon(name, extraClass = "") {
  return `<i data-lucide="${name}" class="w-5 h-5 ${extraClass}" aria-hidden="true"></i>`;
}

function refreshIcons() {
  if (window.lucide?.createIcons) {
    window.lucide.createIcons();
  }
}

function renderActions(job) {
  const canDownload = job.state === "completed" && job.download_available;
  const downloadButton = canDownload
    ? `<a href="/api/jobs/${job.id}/download" class="inline-flex items-center justify-center bg-green-600 text-white w-10 h-10 rounded-lg hover:bg-green-700 transition" title="Download" aria-label="Download">${renderIcon("download")}</a>`
    : `<button type="button" disabled class="inline-flex items-center justify-center bg-gray-200 text-gray-400 w-10 h-10 rounded-lg cursor-not-allowed" title="Download unavailable" aria-label="Download unavailable">${renderIcon("download")}</button>`;
  const renderLogLink = () =>
    `<a href="/jobs/${job.id}/log" target="_blank" class="inline-flex items-center justify-center border border-blue-200 text-blue-600 w-10 h-10 rounded-lg hover:bg-blue-50 hover:text-blue-700 transition" title="View log" aria-label="View log">${renderIcon("file-text")}</a>`;
  const cancelButton = `<button type="button" data-cancel-job="${job.id}" class="inline-flex items-center justify-center bg-red-600 text-white w-10 h-10 rounded-lg hover:bg-red-700 transition ml-auto" title="Cancel job" aria-label="Cancel job">${renderIcon("x")}</button>`;

  if (job.state === "completed") {
    const logLink = job.log_path ? renderLogLink() : "";
    return `
      ${downloadButton}
      ${logLink}
    `;
  }

  if (job.state === "queued" || job.state === "running") {
    const logLink = job.log_path ? renderLogLink() : "";
    return `
      ${downloadButton}
      ${logLink}
      ${cancelButton}
    `;
  }

  if (job.log_path) {
    return `
      ${downloadButton}
      ${renderLogLink()}
    `;
  }

  return downloadButton;
}

function renderJobCard(job) {
  const expanded = expandedJobs.has(job.id);
  const eta = getEta(job);
  const showProgress = job.state === "running" || job.state === "queued";
  const currentTime = formatCurrentTime(job.progress?.current);
  const totalDuration = job.progress?.duration
    ? formatDuration(job.progress.duration)
    : "-";
  const statusSummary = showProgress
    ? `
      <span class="text-sm text-gray-500">${currentTime} / ${totalDuration}</span>
      <span class="text-sm text-green-600">ETA ${eta}</span>
    `
    : job.error_message
      ? `<span class="text-sm text-red-600 truncate max-w-full">${job.error_message}</span>`
      : "";
  const outputRow = job.output_path
    ? `
      <div class="md:col-span-2">
        <dt class="text-sm text-gray-500">Output</dt>
        <dd class="text-gray-700 break-all">${job.output_path}</dd>
      </div>
    `
    : "";
  const errorRow = job.error_message
    ? `
      <div class="md:col-span-2">
        <dt class="text-sm text-gray-500">Error</dt>
        <dd class="text-red-600 break-words">${job.error_message}</dd>
      </div>
    `
    : "";
  const progressDetails = showProgress
    ? `
      <div>
        <dt class="text-sm text-gray-500">Speed</dt>
        <dd class="text-gray-700">${job.speed || "-"}</dd>
      </div>
      <div>
        <dt class="text-sm text-gray-500">Duration</dt>
        <dd class="text-gray-700">${job.progress?.duration ? formatDuration(job.progress.duration) : "-"}</dd>
      </div>
    `
    : "";

  return `
    <article class="border border-gray-200 rounded-xl bg-gray-50 overflow-hidden">
      <div class="px-5 py-4 bg-white">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-3">
              <strong class="text-gray-900">${job.item_name}</strong>
              <span class="px-3 py-1 text-sm font-medium rounded-full ${getStateClasses(job.state)}">${job.state}</span>
              <span class="text-gray-500 text-sm">${job.preset?.name || job.preset}</span>
              ${statusSummary}
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-3 min-w-[120px]">
            ${renderActions(job)}
          </div>
        </div>
      </div>
      <button
        type="button"
        data-toggle-job="${job.id}"
        class="flex w-full items-center justify-center bg-gray-100 text-gray-500 h-6 hover:bg-gray-200 hover:text-gray-700 transition border-t border-gray-200"
        aria-expanded="${expanded ? "true" : "false"}"
        title="${expanded ? "Collapse details" : "Expand details"}"
        aria-label="${expanded ? "Collapse details" : "Expand details"}"
      >
        <span class="transform ${expanded ? "rotate-180" : ""}">${renderIcon("chevron-down")}</span>
      </button>
      <div class="${expanded ? "block" : "hidden"} px-5 pb-5 border-t border-gray-200 bg-gray-50">
        <dl class="grid gap-4 pt-5 md:grid-cols-2">
          <div>
            <dt class="text-sm text-gray-500">ID</dt>
            <dd class="font-mono text-sm text-gray-700 break-all">${job.id}</dd>
          </div>
          <div>
            <dt class="text-sm text-gray-500">State</dt>
            <dd class="font-medium text-gray-700">${job.state}</dd>
          </div>
          <div>
            <dt class="text-sm text-gray-500">Created</dt>
            <dd class="text-gray-700">${job.created_at || "-"}</dd>
          </div>
          <div>
            <dt class="text-sm text-gray-500">Started</dt>
            <dd class="text-gray-700">${job.started_at || "-"}</dd>
          </div>
          <div>
            <dt class="text-sm text-gray-500">Finished</dt>
            <dd class="text-gray-700">${job.finished_at || "-"}</dd>
          </div>
          ${progressDetails}
          ${outputRow}
          ${errorRow}
        </dl>
      </div>
    </article>
  `;
}

async function cancelJob(jobId) {
  if (!window.confirm("Cancel this job?")) {
    return;
  }

  try {
    const response = await fetch(`/api/jobs/${jobId}/cancel`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error("Failed to cancel");
    }
    await loadJobs();
  } catch (error) {
    window.alert("Failed to cancel");
  }
}

function bindJobEvents() {
  document.querySelectorAll("[data-toggle-job]").forEach((button) => {
    button.addEventListener("click", () => {
      const jobId = button.dataset.toggleJob;
      if (expandedJobs.has(jobId)) {
        expandedJobs.delete(jobId);
      } else {
        expandedJobs.add(jobId);
      }
      loadJobs();
    });
  });

  document.querySelectorAll("[data-cancel-job]").forEach((button) => {
    button.addEventListener("click", () => cancelJob(button.dataset.cancelJob));
  });
}

async function loadJobs() {
  const container = document.getElementById("jobs-list");
  if (!container) {
    return;
  }

  try {
    const resp = await fetch("/api/jobs");
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }

    const data = await resp.json();
    const jobs = data.jobs || [];

    if (requestedJobId && jobs.some((job) => job.id === requestedJobId)) {
      expandedJobs.add(requestedJobId);
    }

    if (jobs.length === 0) {
      container.innerHTML = '<p class="text-gray-500">No jobs yet.</p>';
      return;
    }

    container.innerHTML = `<div class="space-y-4">${jobs.map(renderJobCard).join("")}</div>`;
    bindJobEvents();
    refreshIcons();
  } catch (error) {
    container.innerHTML = '<p class="text-red-600">Failed to load.</p>';
  }
}

function stopPoll() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

function startPoll() {
  stopPoll();
  loadJobs();
  pollInterval = setInterval(loadJobs, pollIntervalMs);
}

document.getElementById("poll-toggle")?.addEventListener("change", (event) => {
  if (event.target.checked) {
    startPoll();
    return;
  }

  stopPoll();
});

startPoll();
