// Tabs: switch between a dataset job and a custom job description.
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll("[data-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.panel !== tab.dataset.tab;
    });
  });
});

// Show the selected dataset job's requirements under the dropdown.
const jobSelect = document.getElementById("job_id");
if (jobSelect) {
  const preview = document.querySelector(".job-preview");
  jobSelect.addEventListener("change", () => {
    const opt = jobSelect.selectedOptions[0];
    preview.querySelector('[data-field="exp"]').textContent = opt.dataset.exp;
    preview.querySelector('[data-field="edu"]').textContent = opt.dataset.edu;
    preview.querySelector('[data-field="skills"]').textContent = opt.dataset.skills || "Not specified";
    preview.hidden = false;
  });
}

// Ranking can take a few seconds: disable the button so it isn't clicked twice.
document.querySelectorAll(".rank-form").forEach((form) => {
  form.addEventListener("submit", () => {
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "Ranking resumes…";
  });
});
