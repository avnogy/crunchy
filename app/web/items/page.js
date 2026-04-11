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
    const resultDiv = document.getElementById("job-result");
    if (!resultDiv) {
      return;
    }

    resultDiv.innerHTML = '<p class="text-gray-600">Creating job...</p>';

    try {
      const { ok, result } = await createJob({
        item_id: form.item_id.value,
        item_name: form.item_name.value,
        preset: form.preset.value,
      });

      if (ok) {
        const message = result?.deduped
          ? "Job already exists!"
          : "Job created!";
        resultDiv.innerHTML = `<p class="text-green-600">${message} <a href="/jobs?job=${result.job.id}" class="text-blue-600 hover:underline">View job</a></p>`;
        return;
      }

      resultDiv.innerHTML = `<p class="text-red-600">Error: ${result?.detail || "Unknown error"}</p>`;
    } catch (error) {
      resultDiv.innerHTML = '<p class="text-red-600">Failed to create job.</p>';
    }
  });

document.getElementById("select-all")?.addEventListener("change", (event) => {
  document.querySelectorAll('input[name="item_ids"]').forEach((checkbox) => {
    checkbox.checked = event.target.checked;
  });
});

document
  .getElementById("batch-download-form")
  ?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const form = event.target;
    const checked = document.querySelectorAll('input[name="item_ids"]:checked');
    const resultDiv = document.getElementById("batch-result");
    if (!resultDiv) {
      return;
    }

    if (checked.length === 0) {
      resultDiv.innerHTML =
        '<p class="text-red-600">Select at least one episode.</p>';
      return;
    }

    resultDiv.innerHTML = '<p class="text-gray-600">Creating jobs...</p>';

    const preset = form.preset.value;
    let created = 0;
    let deduped = 0;
    const createdIds = [];
    const errors = [];

    for (const checkbox of checked) {
      try {
        const { ok, result } = await createJob({
          item_id: checkbox.value,
          item_name: checkbox.dataset.name,
          preset,
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
      const focusJob = createdIds[0] ? `?job=${createdIds[0]}` : "";
      const parts = [];
      if (created > 0) {
        parts.push(`Created ${created} job(s)`);
      }
      if (deduped > 0) {
        parts.push(`reused ${deduped} existing job(s)`);
      }
      resultDiv.innerHTML = `<p class="text-green-600">${parts.join(", ")}. <a href="/jobs${focusJob}" class="text-blue-600 hover:underline">View jobs</a></p>`;
      return;
    }

    resultDiv.innerHTML = `<p class="text-red-600">Failed: ${errors.join(", ")}</p>`;
  });
