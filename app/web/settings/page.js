const EMPTY_PRESET = {
  maxHeight: 0,
  videoBitrate: 0,
  audioBitrate: 0,
  name: "",
  videoCodec: "",
  audioCodec: "",
  segmentContainer: "",
};
let presets = {};
let storedApiKeyLength = 0;
let storedAppPasswordLength = 0;

function setFieldInvalid(input, invalid) {
  if (!input) {
    return;
  }

  input.classList.toggle("border-red-500", invalid);
  input.classList.toggle("focus:ring-red-500", invalid);
  input.classList.toggle("focus:border-red-500", invalid);
  input.classList.toggle("border-gray-200", !invalid);
  input.classList.toggle("focus:ring-blue-500", !invalid);
  input.classList.toggle("focus:border-transparent", !invalid);
}

function validateRequiredJellyfinFields() {
  const apiKeyInput = document.getElementById("jellyfin-api-key");
  const userIdInput = document.getElementById("jellyfin-user-id");
  const apiKeyHelp = document.getElementById("jellyfin-api-key-help");
  const requiredMessage = document.getElementById("jellyfin-required-message");

  const apiKeyMissing = storedApiKeyLength === 0 && !apiKeyInput?.value.trim();
  const userIdMissing = !userIdInput?.value.trim();

  setFieldInvalid(apiKeyInput, apiKeyMissing);
  setFieldInvalid(userIdInput, userIdMissing);

  if (apiKeyHelp) {
    apiKeyHelp.textContent =
      storedApiKeyLength > 0
        ? `Leave blank to keep current (${storedApiKeyLength} chars set)`
        : "Required";
    apiKeyHelp.className = apiKeyMissing
      ? "text-xs text-red-600 mt-1"
      : "text-xs text-gray-500 mt-1";
  }

  if (requiredMessage) {
    requiredMessage.classList.toggle(
      "hidden",
      !(apiKeyMissing || userIdMissing),
    );
  }

  return !(apiKeyMissing || userIdMissing);
}

async function clearDirectory(endpoint, label, button) {
  if (
    !window.confirm(
      `This will permanently delete everything currently inside the ${label}. This cannot be undone.\n\nContinue?`,
    )
  ) {
    return;
  }

  const result = document.getElementById("paths-result");
  const originalText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "Emptying...";
  }

  try {
    const resp = await fetch(endpoint, { method: "POST" });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
      throw new Error(data?.detail || "Failed");
    }

    if (result) {
      result.textContent = `Emptied ${label}: removed ${data.cleared} item(s).`;
      result.className = "text-sm text-green-600";
    }
  } catch (error) {
    if (result) {
      result.textContent = `Failed to empty ${label}.`;
      result.className = "text-sm text-red-600";
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function renderPresets() {
  const container = document.getElementById("presets-list");
  container.innerHTML = "";

  Object.entries(presets).forEach(([key, preset]) => {
    const displayPreset = { ...EMPTY_PRESET, ...preset };
    const div = document.createElement("div");
    div.className = "flex gap-4 items-start p-4 bg-gray-50 rounded-lg";
    div.innerHTML = `
            <div class="flex-1 space-y-2">
                <input type="text" data-preset-key="${key}" data-field="name" value="${displayPreset.name}" class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Name">
                <div class="grid grid-cols-3 gap-2">
                    <input type="number" data-preset-key="${key}" data-field="maxHeight" value="${displayPreset.maxHeight}" class="px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Height">
                    <input type="number" data-preset-key="${key}" data-field="videoBitrate" value="${displayPreset.videoBitrate}" class="px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Video bitrate">
                    <input type="number" data-preset-key="${key}" data-field="audioBitrate" value="${displayPreset.audioBitrate}" class="px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Audio bitrate">
                </div>
                <div class="grid grid-cols-3 gap-2">
                    <input type="text" data-preset-key="${key}" data-field="videoCodec" value="${displayPreset.videoCodec}" class="px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Video codec">
                    <input type="text" data-preset-key="${key}" data-field="audioCodec" value="${displayPreset.audioCodec}" class="px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Audio codec">
                    <input type="text" data-preset-key="${key}" data-field="segmentContainer" value="${displayPreset.segmentContainer}" class="px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Segment container">
                </div>
            </div>
            <button type="button" data-delete="${key}" class="text-red-600 hover:text-red-700 p-2">×</button>
        `;
    container.appendChild(div);
  });

  container.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", () => {
      delete presets[btn.dataset.delete];
      renderPresets();
    });
  });

  container.querySelectorAll("input[data-preset-key]").forEach((input) => {
    input.addEventListener("input", () => {
      const key = input.dataset.presetKey;
      const field = input.dataset.field;
      const val =
        field.includes("Height") || field.includes("Bitrate")
          ? parseInt(input.value, 10) || 0
          : input.value;
      presets[key][field] = val;
    });
  });
}

document.getElementById("add-preset")?.addEventListener("click", () => {
  const key = "custom-" + Date.now().toString(36);
  presets[key] = {
    maxHeight: 720,
    videoBitrate: 1400000,
    audioBitrate: 128000,
    name: "Custom",
  };
  renderPresets();
});

async function loadSettings() {
  try {
    const resp = await fetch("/api/settings");
    if (!resp.ok) throw new Error("Failed");
    const data = await resp.json();
    const settings = data.settings;
    storedApiKeyLength = Number(settings.jellyfin_api_key_length) || 0;
    storedAppPasswordLength = Number(settings.app_password_length) || 0;

    Object.keys(settings).forEach((key) => {
      const input = document.querySelector(`[name="${key}"]`);
      if (input) {
        if (key === "presets") {
          presets = settings.presets || {};
          renderPresets();
        } else if (key === "ffmpeg_flags" && Array.isArray(settings[key])) {
          input.value = settings[key].join(" ");
        } else {
          input.value = settings[key];
        }
      }
    });
    const apiKeyInput = document.getElementById("jellyfin-api-key");
    if (apiKeyInput && storedApiKeyLength > 0) {
      apiKeyInput.placeholder = "\u2022".repeat(
        Math.min(storedApiKeyLength, 16),
      );
    }
    const appPasswordInput = document.getElementById("app-password");
    const appPasswordHelp = document.getElementById("app-password-help");
    if (appPasswordInput && storedAppPasswordLength > 0) {
      appPasswordInput.placeholder = "\u2022".repeat(
        Math.min(storedAppPasswordLength, 16),
      );
    }
    if (appPasswordHelp) {
      appPasswordHelp.textContent =
        storedAppPasswordLength > 0
          ? `Leave blank to keep current (${storedAppPasswordLength} chars set)`
          : "Required";
    }
    validateRequiredJellyfinFields();
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

document
  .getElementById("settings-form")
  ?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const result = document.getElementById("save-result");

    if (!validateRequiredJellyfinFields()) {
      if (result) {
        result.textContent = "API key and User ID are required.";
        result.className = "text-sm text-red-600";
      }
      return;
    }

    const data = {
      jellyfin_api_url: formData.get("jellyfin_api_url"),
      jellyfin_api_key: formData.get("jellyfin_api_key"),
      jellyfin_user_id: formData.get("jellyfin_user_id"),
      app_password: formData.get("app_password"),
      transcoding_temp_dir: formData.get("transcoding_temp_dir"),
      output_dir: formData.get("output_dir"),
      app_host: formData.get("app_host"),
      app_port: parseInt(formData.get("app_port"), 10) || 8000,
      max_concurrent_jobs:
        parseInt(formData.get("max_concurrent_jobs"), 10) || 1,
      jobs_poll_interval_ms: Math.max(
        500,
        parseInt(formData.get("jobs_poll_interval_ms"), 10) || 3000,
      ),
      log_level: formData.get("log_level"),
      presets,
      ffmpeg_flags: (formData.get("ffmpeg_flags") || "")
        .split(/\s+/)
        .filter(Boolean),
    };

    try {
      const resp = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (resp.ok) {
        const saved = await resp.json();
        presets = saved?.settings?.presets || presets;
        storedApiKeyLength =
          Number(saved?.settings?.jellyfin_api_key_length) ||
          storedApiKeyLength;
        storedAppPasswordLength =
          Number(saved?.settings?.app_password_length) ||
          storedAppPasswordLength;
        result.textContent = "Saved!";
        result.className = "text-sm text-green-600";
        const apiKeyInput = document.getElementById("jellyfin-api-key");
        if (apiKeyInput) {
          apiKeyInput.value = "";
          apiKeyInput.placeholder = "\u2022".repeat(
            Math.min(storedApiKeyLength, 16),
          );
        }
        const apiKeyHelp = document.getElementById("jellyfin-api-key-help");
        if (apiKeyHelp) {
          apiKeyHelp.textContent = `Leave blank to keep current (${storedApiKeyLength} chars set)`;
          apiKeyHelp.className = "text-xs text-gray-500 mt-1";
        }
        const appPasswordInput = document.getElementById("app-password");
        if (appPasswordInput) {
          appPasswordInput.value = "";
          appPasswordInput.placeholder = "\u2022".repeat(
            Math.min(storedAppPasswordLength, 16),
          );
        }
        const appPasswordHelp = document.getElementById("app-password-help");
        if (appPasswordHelp) {
          appPasswordHelp.textContent = `Leave blank to keep current (${storedAppPasswordLength} chars set)`;
        }
        renderPresets();
      } else {
        result.textContent = "Error saving";
        result.className = "text-sm text-red-600";
      }
    } catch (e) {
      result.textContent = "Error saving";
      result.className = "text-sm text-red-600";
    }

    setTimeout(() => {
      result.textContent = "";
    }, 3000);
  });

async function updatePreview() {
  const flagInput = document.querySelector('[name="ffmpeg_flags"]');
  const raw = flagInput?.value ?? "";
  const flags = raw.trim().split(/\s+/).filter(Boolean);

  try {
    const resp = await fetch("/api/ffmpeg-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ffmpeg_flags: flags }),
    });

    if (!resp.ok) {
      const errorData = await resp.json();
      const errorMessage = errorData.detail || "Invalid flags";
      const previewEl = document.getElementById("ffmpeg-preview");
      previewEl.textContent = errorMessage;
      previewEl.className =
        "bg-gray-800 text-red-400 text-xs p-4 rounded-lg overflow-x-auto font-mono mt-1";
      flagInput.classList.add(
        "border-red-500",
        "focus:ring-red-500",
        "focus:border-red-500",
      );
      flagInput.classList.remove(
        "border-gray-200",
        "focus:ring-blue-500",
        "focus:border-transparent",
      );
      return;
    }

    const data = await resp.json();
    const previewEl = document.getElementById("ffmpeg-preview");
    previewEl.textContent = data.command.join(" ");
    previewEl.className =
      "bg-gray-800 text-green-400 text-xs p-4 rounded-lg overflow-x-auto font-mono mt-1";
    flagInput.classList.remove(
      "border-red-500",
      "focus:ring-red-500",
      "focus:border-red-500",
    );
    flagInput.classList.add(
      "border-gray-200",
      "focus:ring-blue-500",
      "focus:border-transparent",
    );
  } catch (e) {
    const previewEl = document.getElementById("ffmpeg-preview");
    previewEl.textContent = "Error loading preview";
    previewEl.className =
      "bg-gray-800 text-red-400 text-xs p-4 rounded-lg overflow-x-auto font-mono mt-1";
    flagInput.classList.add(
      "border-red-500",
      "focus:ring-red-500",
      "focus:border-red-500",
    );
    flagInput.classList.remove(
      "border-gray-200",
      "focus:ring-blue-500",
      "focus:border-transparent",
    );
  }
}

document
  .querySelector('[name="ffmpeg_flags"]')
  ?.addEventListener("input", updatePreview);

document
  .getElementById("clear-temp-dir")
  ?.addEventListener("click", (event) => {
    clearDirectory(
      "/api/settings/clear-temp",
      "temp folder",
      event.currentTarget,
    );
  });

document
  .getElementById("clear-output-dir")
  ?.addEventListener("click", (event) => {
    clearDirectory(
      "/api/settings/clear-output",
      "output folder",
      event.currentTarget,
    );
  });

document.getElementById("jellyfin-api-key")?.addEventListener("input", () => {
  validateRequiredJellyfinFields();
});

document.getElementById("jellyfin-user-id")?.addEventListener("input", () => {
  validateRequiredJellyfinFields();
});

loadSettings();
renderPresets();
updatePreview();
