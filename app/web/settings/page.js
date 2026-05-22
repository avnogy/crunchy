const PRESET_NUMBER_FIELDS = new Set([
  "maxHeight",
  "videoBitrate",
  "audioBitrate",
]);
const PRESET_FIELDS = [
  {
    name: "name",
    type: "text",
    placeholder: "Name",
    className: "md:col-span-3",
  },
  { name: "maxHeight", type: "number", placeholder: "Height" },
  { name: "videoBitrate", type: "number", placeholder: "Video bitrate" },
  { name: "audioBitrate", type: "number", placeholder: "Audio bitrate" },
  { name: "videoCodec", type: "text", placeholder: "Video codec" },
  { name: "audioCodec", type: "text", placeholder: "Audio codec" },
  { name: "segmentContainer", type: "text", placeholder: "Segment container" },
];

let newPresetTemplate = {};
let presets = {};
let storedApiKeyLength = 0;
let storedAppPasswordLength = 0;

function presetFieldClass() {
  return "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800";
}

function renderPresetField(key, preset, field) {
  return `
    <label class="block ${field.className || ""}">
      <span class="mb-1.5 block text-xs font-medium uppercase tracking-[0.16em] text-slate-400">
        ${window.ui.escapeHtml(field.placeholder)}
      </span>
      <input
        type="${field.type}"
        data-preset-key="${window.ui.escapeHtml(key)}"
        data-field="${field.name}"
        value="${window.ui.escapeHtml(preset[field.name])}"
        class="${presetFieldClass()}"
        placeholder="${window.ui.escapeHtml(field.placeholder)}"
      >
    </label>
  `;
}

function renderPresetCard(key, preset) {
  return `
    <section class="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-start">
        <div class="grid flex-1 gap-3 md:grid-cols-3">
          ${PRESET_FIELDS.map((field) => renderPresetField(key, preset, field)).join("")}
        </div>
        <button
          type="button"
          data-delete-preset="${window.ui.escapeHtml(key)}"
          class="ui-button-danger rounded-lg border px-3 py-2 text-sm font-medium transition"
        >
          Remove
        </button>
      </div>
    </section>
  `;
}

function renderPresets() {
  const container = document.getElementById("presets-list");
  if (!container) {
    return;
  }

  container.innerHTML = Object.entries(presets)
    .map(([key, preset]) => renderPresetCard(key, preset))
    .join("");
}

function updateSecretPlaceholders() {
  const apiKeyInput = document.getElementById("jellyfin-api-key");
  const apiKeyHelp = document.getElementById("jellyfin-api-key-help");
  if (apiKeyInput) {
    apiKeyInput.placeholder =
      storedApiKeyLength > 0
        ? "\u2022".repeat(Math.min(storedApiKeyLength, 16))
        : "";
  }
  if (apiKeyHelp) {
    apiKeyHelp.textContent =
      storedApiKeyLength > 0
        ? `Current value saved (${storedApiKeyLength} chars)`
        : "";
  }

  const appPasswordInput = document.getElementById("app-password");
  const appPasswordHelp = document.getElementById("app-password-help");
  if (appPasswordInput) {
    appPasswordInput.placeholder =
      storedAppPasswordLength > 0
        ? "\u2022".repeat(Math.min(storedAppPasswordLength, 16))
        : "";
  }
  if (appPasswordHelp) {
    appPasswordHelp.textContent =
      storedAppPasswordLength > 0
        ? `Current value saved (${storedAppPasswordLength} chars)`
        : "Required";
  }
}

function updateFfmpegPreviewState(message, isError) {
  const previewEl = document.getElementById("ffmpeg-preview");
  const flagInput = document.querySelector('[name="ffmpeg_flags"]');
  if (!previewEl || !flagInput) {
    return;
  }

  previewEl.textContent = message;
  previewEl.className = `overflow-x-auto rounded-lg border border-slate-200 p-4 font-mono text-xs ${
    isError ? "ui-code-surface-error" : "ui-code-surface"
  }`;

  flagInput.classList.toggle("ui-input-error", isError);
  flagInput.classList.toggle("border-slate-300", !isError);
}

async function clearDirectory(endpoint, label, button) {
  if (
    !window.confirm(
      `This will permanently delete everything currently inside the ${label}. This cannot be undone.\n\nContinue?`,
    )
  ) {
    return;
  }

  try {
    const data = await window.ui.withBusyState(button, "Emptying...", () =>
      window.ui.request(endpoint, { method: "POST" }),
    );
    toast.success(`Emptied ${label}: removed ${data.cleared} item(s)`);
  } catch (error) {
    toast.error(`Failed to empty ${label}`);
  }
}

function populateForm(settings) {
  Object.entries(settings).forEach(([key, value]) => {
    const input = document.querySelector(`[name="${key}"]`);
    if (!input) {
      return;
    }

    input.value =
      key === "ffmpeg_flags" && Array.isArray(value) ? value.join(" ") : value;
  });
}

async function loadSettings() {
  try {
    const data = await window.ui.request("/api/settings");
    const settings = data.settings;

    storedApiKeyLength = Number(settings.jellyfin_api_key_length) || 0;
    storedAppPasswordLength = Number(settings.app_password_length) || 0;
    newPresetTemplate = settings.new_preset_template || {};
    presets = settings.presets || {};

    populateForm(settings);
    renderPresets();
    updateSecretPlaceholders();
    updatePreview();
  } catch (error) {
    toast.error("Failed to load settings");
  }
}

function getSettingsPayload(form) {
  const formData = new FormData(form);
  return {
    jellyfin_api_url: formData.get("jellyfin_api_url"),
    jellyfin_api_key: formData.get("jellyfin_api_key"),
    jellyfin_user_id: formData.get("jellyfin_user_id"),
    app_password: formData.get("app_password"),
    app_host: formData.get("app_host"),
    app_port: formData.get("app_port"),
    redis_host: formData.get("redis_host"),
    redis_port: formData.get("redis_port"),
    jobs_poll_interval_ms: formData.get("jobs_poll_interval_ms"),
    log_level: formData.get("log_level"),
    presets,
    ffmpeg_flags: formData.get("ffmpeg_flags") || "",
  };
}

function refreshStoredSecretState(savedSettings) {
  newPresetTemplate = savedSettings?.new_preset_template || newPresetTemplate;
  presets = savedSettings?.presets || presets;
  storedApiKeyLength =
    Number(savedSettings?.jellyfin_api_key_length) || storedApiKeyLength;
  storedAppPasswordLength =
    Number(savedSettings?.app_password_length) || storedAppPasswordLength;

  const apiKeyInput = document.getElementById("jellyfin-api-key");
  const appPasswordInput = document.getElementById("app-password");
  if (apiKeyInput) {
    apiKeyInput.value = "";
  }
  if (appPasswordInput) {
    appPasswordInput.value = "";
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector('button[type="submit"]');

  if (!form.reportValidity()) {
    return;
  }

  try {
    const saved = await window.ui.withBusyState(submitButton, "Saving...", () =>
      window.ui.requestJson("/api/settings", {
        method: "POST",
        body: getSettingsPayload(form),
      }),
    );

    refreshStoredSecretState(saved?.settings);
    updateSecretPlaceholders();
    renderPresets();
    updatePreview();
    toast.success("Saved");
  } catch (error) {
    toast.error(error.data?.detail || "Error saving");
  }
}

async function updatePreview() {
  const raw = document.querySelector('[name="ffmpeg_flags"]')?.value ?? "";

  try {
    const data = await window.ui.requestJson("/api/ffmpeg-preview", {
      method: "POST",
      body: { ffmpeg_flags: raw },
    });
    updateFfmpegPreviewState(data.command.join(" "), false);
  } catch (error) {
    updateFfmpegPreviewState(error.data?.detail || "Invalid flags", true);
  }
}

async function checkRedisHealth(button) {
  try {
    await window.ui.withBusyState(button, "Checking...", () =>
      window.ui.request("/api/redis-health"),
    );
    toast.success("Redis is reachable with the saved host and port");
  } catch (error) {
    toast.error("Redis check failed for the saved host and port");
  }
}

function addPreset() {
  const key = `custom-${Date.now().toString(36)}`;
  presets[key] = { ...newPresetTemplate };
  renderPresets();
}

document
  .getElementById("settings-form")
  ?.addEventListener("submit", saveSettings);
document
  .querySelector('[name="ffmpeg_flags"]')
  ?.addEventListener("input", updatePreview);

document.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete-preset]");
  if (deleteButton) {
    delete presets[deleteButton.dataset.deletePreset];
    renderPresets();
    return;
  }

  if (event.target.id === "add-preset") {
    addPreset();
    return;
  }

  if (event.target.id === "check-redis-health") {
    checkRedisHealth(event.target);
    return;
  }

  if (event.target.id === "clear-temp-dir") {
    clearDirectory("/api/settings/clear-temp", "temp folder", event.target);
    return;
  }

  if (event.target.id === "clear-output-dir") {
    clearDirectory("/api/settings/clear-output", "output folder", event.target);
  }
});

document.addEventListener("input", (event) => {
  if (!event.target.matches("input[data-preset-key]")) {
    return;
  }

  const { presetKey: key, field } = event.target.dataset;
  if (!key || !field || !presets[key]) {
    return;
  }

  presets[key][field] = PRESET_NUMBER_FIELDS.has(field)
    ? parseInt(event.target.value, 10) || 0
    : event.target.value;
});

loadSettings();
renderPresets();
