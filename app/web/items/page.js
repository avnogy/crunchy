const EPISODE_CARD_SELECTED_CLASSES = ["ui-selected-card"];
const EPISODE_CARD_IDLE_CLASSES = ["border-slate-200", "bg-white"];
const EPISODE_BADGE_SELECTED_CLASSES = ["ui-selected-indicator"];
const EPISODE_BADGE_IDLE_CLASSES = [
  "border-slate-300",
  "bg-white",
  "text-transparent",
];

function isInteractiveTarget(target) {
  return Boolean(
    target.closest(
      "button, a, select, option, input, label, textarea, [role='button']",
    ),
  );
}

async function createJob(payload) {
  try {
    const result = await window.ui.requestJson("/api/jobs", {
      method: "POST",
      body: payload,
    });
    return { ok: true, result };
  } catch (error) {
    return { ok: false, result: error.data || { detail: error.message } };
  }
}

function getEpisodeCheckboxes() {
  return window.ui.queryAll('input[name="item_ids"]');
}

function syncEpisodeCardState(checkbox) {
  const card = checkbox.closest(".episode-card");
  if (!card) {
    return;
  }

  const checked = checkbox.checked;
  card.dataset.selected = checked ? "true" : "false";
  window.ui.toggleClasses(
    card,
    checked,
    EPISODE_CARD_SELECTED_CLASSES,
    EPISODE_CARD_IDLE_CLASSES,
  );

  const badge = card.querySelector(".episode-selection-indicator");
  window.ui.toggleClasses(
    badge,
    checked,
    EPISODE_BADGE_SELECTED_CLASSES,
    EPISODE_BADGE_IDLE_CLASSES,
  );
}

function updateSelectionSummary() {
  const selectedCount = getEpisodeCheckboxes().filter(
    (checkbox) => checkbox.checked,
  ).length;
  const countEl = document.getElementById("selected-count");
  const suffixEl = document.getElementById("selected-count-suffix");

  if (countEl) {
    countEl.textContent = String(selectedCount);
  }
  if (suffixEl) {
    suffixEl.textContent = selectedCount === 1 ? "" : "s";
  }
}

function setCheckedState(checkbox, checked) {
  checkbox.checked = checked;
  syncEpisodeCardState(checkbox);
}

function getStreamIndex(select) {
  if (!select || select.value === "") {
    return null;
  }

  return Number(select.value);
}

async function submitSingleDownload(form) {
  const submitButton = form.querySelector('button[type="submit"]');

  await window.ui.withBusyState(submitButton, "Saving...", async () => {
    const { ok, result } = await createJob({
      item_id: form.item_id.value,
      item_name: form.item_name.value,
      preset: form.preset.value,
      audio_stream_index: getStreamIndex(form.audio_stream_index),
      subtitle_stream_index: getStreamIndex(form.subtitle_stream_index),
    });

    if (ok) {
      toast.success("Job created!");
      return;
    }

    toast.error(result?.detail || "Unknown error");
  });
}

async function submitBatchDownload(form) {
  const checked = getEpisodeCheckboxes().filter((checkbox) => checkbox.checked);
  if (checked.length === 0) {
    toast.error("Select at least one episode");
    return;
  }

  const submitButton = form.querySelector('button[type="submit"]');
  const preset = form.querySelector('[name="preset"]')?.value;
  if (!preset) {
    toast.error("Missing preset");
    return;
  }

  await window.ui.withBusyState(submitButton, "Queueing...", async () => {
    let created = 0;
    const errors = [];

    for (const checkbox of checked) {
      try {
        const audioSelect = document.querySelector(
          `select[data-item-id="${CSS.escape(checkbox.value)}"][data-stream-kind="audio"]`,
        );
        const subtitleSelect = document.querySelector(
          `select[data-item-id="${CSS.escape(checkbox.value)}"][data-stream-kind="subtitle"]`,
        );
        const { ok, result } = await createJob({
          item_id: checkbox.value,
          item_name: checkbox.dataset.name,
          preset,
          audio_stream_index: getStreamIndex(audioSelect),
          subtitle_stream_index: getStreamIndex(subtitleSelect),
        });

        if (ok) {
          created += 1;
        } else {
          errors.push(result?.detail || "Unknown error");
        }
      } catch (error) {
        errors.push(error.message);
      }
    }

    if (created > 0) {
      toast.success(`Created ${created} job(s)`);
      return;
    }

    toast.error(`Failed: ${errors.join(", ")}`);
  });
}

function applyBatchAction(action) {
  getEpisodeCheckboxes().forEach((checkbox) => {
    if (action === "all") {
      setCheckedState(checkbox, true);
    } else if (action === "none") {
      setCheckedState(checkbox, false);
    } else if (action === "invert") {
      setCheckedState(checkbox, !checkbox.checked);
    }
  });

  updateSelectionSummary();
}

function initializeEpisodeCards() {
  getEpisodeCheckboxes().forEach(syncEpisodeCardState);
  updateSelectionSummary();
}

document.addEventListener("change", (event) => {
  if (event.target.matches('input[name="item_ids"]')) {
    syncEpisodeCardState(event.target);
    updateSelectionSummary();
    return;
  }

  if (event.target.id === "batch-preset") {
    const proxy = document.getElementById("batch-preset-mobile-proxy");
    if (proxy) {
      proxy.value = event.target.value;
    }
  }
});

document.addEventListener("click", (event) => {
  const batchActionButton = event.target.closest("[data-batch-action]");
  if (batchActionButton) {
    applyBatchAction(batchActionButton.dataset.batchAction);
    return;
  }

  const card = event.target.closest(".episode-card");
  if (!card || isInteractiveTarget(event.target)) {
    return;
  }

  const checkbox = card.querySelector('input[name="item_ids"]');
  if (!checkbox) {
    return;
  }

  setCheckedState(checkbox, !checkbox.checked);
  updateSelectionSummary();
});

window.ui.query("#download-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitSingleDownload(event.currentTarget);
});

window.ui
  .query("#batch-download-form")
  ?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitBatchDownload(event.currentTarget);
  });

initializeEpisodeCards();
