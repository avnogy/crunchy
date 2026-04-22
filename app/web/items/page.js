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
        audio_stream_index: form.audio_stream_index?.value !== '' ? Number(form.audio_stream_index.value) : null,
      });

      if (ok) {
        const message = result?.deduped
          ? "Job already exists!"
          : "Job created!";
        toast.success(message);
        return;
      }

      toast.error(result?.detail || "Unknown error");
    } catch (error) {
      toast.error("Failed to create job");
    }
  });

document.getElementById("select-all")?.addEventListener("change", (event) => {
  document.querySelectorAll('input[name="item_ids"]').forEach((checkbox) => {
    checkbox.checked = event.target.checked;
  });
});

document.querySelectorAll(".episode-row").forEach((row) => {
  row.addEventListener("click", (event) => {
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (checkbox && event.target !== checkbox) {
      checkbox.checked = !checkbox.checked;
    }
  });
});

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
    toast.info("Creating jobs...");
    let created = 0;
    let deduped = 0;
    const createdIds = [];
    const errors = [];

    for (const checkbox of checked) {
      try {
        const audioSelect = document.querySelector(`select[data-item-id="${CSS.escape(checkbox.value)}"]`);
        const { ok, result } = await createJob({
          item_id: checkbox.value,
          item_name: checkbox.dataset.name,
          preset,
          audio_stream_index: audioSelect?.value !== '' ? Number(audioSelect.value) : null,
        });

        if (ok) {
          if (result?.deduped) {
            deduped += 1;
          } else {
            created += 1;
          }
          createdIds.push(result.job.id);
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
