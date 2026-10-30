const scrapeButton = document.querySelector("#scrape-company");

if (scrapeButton) {
  const form = scrapeButton.closest("form");
  const status = document.querySelector("#scrape-status");
  const websiteInput = form.querySelector('[name="website_url"]');

  scrapeButton.addEventListener("click", async () => {
    const websiteUrl = websiteInput.value.trim();
    if (!websiteUrl) {
      status.textContent = "Escribe la URL HTTPS del sitio oficial primero.";
      status.className = "scrape-status scrape-status-error";
      websiteInput.focus();
      return;
    }

    scrapeButton.disabled = true;
    status.textContent = "Consultando el sitio oficial...";
    status.className = "scrape-status";

    try {
      const response = await fetch(scrapeButton.dataset.previewUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ website_url: websiteUrl }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "No se pudo consultar el sitio.");
      }

      const fields = result.fields || {};
      let completedFields = [];
      for (const [field, value] of Object.entries(fields)) {
        const input = form.elements.namedItem(field);
        if (!input || !value) {
          continue;
        }
        if (field === "website_url" || !input.value.trim()) {
          input.value = value;
          if (field !== "website_url") {
            completedFields.push(field);
          }
        }
      }

      const summary = completedFields.length
        ? `Vista previa lista. Se completaron ${completedFields.length} campo(s); revísalos y edítalos antes de guardar.`
        : "Sitio consultado. No se encontraron campos vacíos para completar; puedes revisar la información y agregarla manualmente.";
      const sourceHost = new URL(result.source_url).hostname;
      status.textContent = `${summary} Fuente: ${sourceHost}`;
      status.className = "scrape-status scrape-status-success";
    } catch (error) {
      status.textContent = error.message;
      status.className = "scrape-status scrape-status-error";
    } finally {
      scrapeButton.disabled = false;
    }
  });
}
