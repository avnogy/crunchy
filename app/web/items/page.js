async function createJob(payload) {
  const resp = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let result = null;
  try {
    result = await resp.json();
  } catch (error) {
    result = null;
  }

  return { ok: resp.ok, result };
}

function isInteractiveTarget(target) {
  return Boolean(
    target.closest(
      "button, a, select, option, input, label, textarea, [role='button']",
    ),
  );
}

function syncEpisodeCardState(card, checked) {
  card.dataset.selected = checked ? "true" : "false";
  card.classList.toggle("border-blue-400", checked);
  card.classList.toggle("bg-blue-50", checked);
  card.classList.toggle("shadow-md", checked);
  card.classList.toggle("border-gray-200", !checked);
  card.classList.toggle("bg-gray-50", !checked);
  card.classList.toggle("shadow-sm", !checked);

  const badge = card.querySelector(".episode-selection-indicator");
  if (badge) {
    badge.classList.toggle("border-blue-600", checked);
    badge.classList.toggle("bg-blue-600", checked);
    badge.classList.toggle("text-white", checked);
    badge.classList.toggle("border-gray-300", !checked);
    badge.classList.toggle("bg-white", !checked);
    badge.classList.toggle("text-transparent", !checked);
  }
}

function updateSelectionSummary() {
  const checkboxes = Array.from(
    document.querySelectorAll('input[name="item_ids"]'),
  );
  if (checkboxes.length === 0) {
    return;
  }

  const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
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
  const card = checkbox.closest(".episode-card");
  if (card) {
    syncEpisodeCardState(card, checked);
  }
}

document
  .getElementById("download-form")
  ?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const form = event.target;

    try {
      const { ok, result } = await createJob({
        item_id: form.item_id.value,
        item_name: form.item_name.value,
        preset: form.preset.value,
        audio_stream_index:
          form.audio_stream_index?.value !== ""
            ? Number(form.audio_stream_index.value)
            : null,
      });

      if (ok) {
        const message = result?.deduped ? "Job already exists!" : "Job created!";
        toast.success(message);
        return;
      }

      toast.error(result?.detail || "Unknown error");
    } catch (error) {
      toast.error("Failed to create job");
    }
  });

const batchPreset = document.getElementById("batch-preset");
const batchPresetProxy = document.getElementById("batch-preset-mobile-proxy");

batchPreset?.addEventListener("change", () => {
  if (batchPresetProxy) {
    batchPresetProxy.value = batchPreset.value;
  }
});

const episodeCheckboxes = Array.from(
  document.querySelectorAll('input[name="item_ids"]'),
);

episodeCheckboxes.forEach((checkbox) => {
  const card = checkbox.closest(".episode-card");
  if (!card) {
    return;
  }

  syncEpisodeCardState(card, checkbox.checked);

  checkbox.addEventListener("change", () => {
    syncEpisodeCardState(card, checkbox.checked);
    updateSelectionSummary();
  });

  card.addEventListener("click", (event) => {
    if (isInteractiveTarget(event.target)) {
      return;
    }

    setCheckedState(checkbox, !checkbox.checked);
    updateSelectionSummary();
  });
});

document.querySelectorAll("[data-batch-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.batchAction;

    episodeCheckboxes.forEach((checkbox) => {
      if (action === "all") {
        setCheckedState(checkbox, true);
      } else if (action === "none") {
        setCheckedState(checkbox, false);
      } else if (action === "invert") {
        setCheckedState(checkbox, !checkbox.checked);
      }
    });

    updateSelectionSummary();
  });
});

updateSelectionSummary();

document
  .getElementById("batch-download-form")
  ?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const form = event.target;
    const checked = document.querySelectorAll('input[name="item_ids"]:checked');
    if (checked.length === 0) {
      toast.error("Select at least one episode");
      return;
    }

    const preset = form.preset.value;
    let created = 0;
    let deduped = 0;
    const errors = [];

    for (const checkbox of checked) {
      try {
        const audioSelect = document.querySelector(
          `select[data-item-id="${CSS.escape(checkbox.value)}"]`,
        );
        const { ok, result } = await createJob({
          item_id: checkbox.value,
          item_name: checkbox.dataset.name,
          preset,
          audio_stream_index:
            audioSelect?.value !== "" ? Number(audioSelect.value) : null,
        });

        if (ok) {
          if (result?.deduped) {
            deduped += 1;
          } else {
            created += 1;
          }
        } else {
          errors.push(result?.detail || "Unknown error");
        }
      } catch (error) {
        errors.push(error.message);
      }
    }

    if (created > 0 || deduped > 0) {
      const parts = [];
      if (created > 0) {
        parts.push(`Created ${created} job(s)`);
      }
      if (deduped > 0) {
        parts.push(`reused ${deduped} existing job(s)`);
      }
      toast.success(parts.join(", "));
      return;
    }

    toast.error("Failed: " + errors.join(", "));
  });
