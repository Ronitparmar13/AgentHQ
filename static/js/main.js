(function () {
    "use strict";

    function setAlert(el, type, message) {
        el.className = "form-allet alert-" + type;
        el.textContent = message;
        el.style.display = "block";
    }

    function clearAlert(el) {
        el.className = "form-alert";
        el.textContent = "";
        el.style.display = "none";
    }

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("project-form");
        if (form) {
            var alertEl = document.getElementById("form-alert");
            var submitBtn = document.getElementById("submit-btn");

            form.addEventListener("submit", function (e) {
                e.preventDefault();
                clearAlert(alertEl);
                submitBtn.disabled = true;
                submitBtn.textContent = "Creating...";

                var data = {
                    title: document.getElementById("title").value.trim(),
                    description: document.getElementById("description").value.trim(),
                };

                fetch("/api/projects", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data),
                })
                .then(function (res) {
                    if (!res.ok) {
                        return res.json().then(function (err) {
                            throw new Error(err.error || "Failed to create project.");
                        });
                    }
                    return res.json();
                })
                .then(function (result) {
                    window.location.href = "/projects/" + result.project.id;
                })
                .catch(function (err) {
                    setAlert(alertEl, "alert-error", err.message);
                    submitBtn.disabled = false;
                    submitBtn.textContent = "Create Project";
                });
            });
        }

        document.querySelectorAll(".task-status-form").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                var taskId = form.dataset.taskId;
                var projectId = form.dataset.projectId;
                var status = form.querySelector("select[name=\"status\"]").value;
                var btn = form.querySelector("button[type=\"submit\"]");
                btn.disabled = true;
                btn.textContent = "Updating...";

                fetch("/api/projects/" + projectId + "/tasks/" + taskId + "/status", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ status: status }),
                })
                .then(function (res) {
                    if (!res.ok) {
                        return res.json().then(function (err) {
                            throw new Error(err.error || "Failed to update status.");
                        });
                    }
                    return res.json();
                })
                .then(function () {
                    window.location.reload();
                })
                .catch(function (err) {
                    alert(err.message);
                    btn.disabled = false;
                    btn.textContent = "Update";
                });
            });
        });

        var planBtn = document.getElementById("plan-btn");
        if (planBtn) {
            planBtn.addEventListener("click", function () {
                var projectId = planBtn.dataset.projectId;
                planBtn.disabled = true;
                planBtn.textContent = "Planning...";

                fetch("/api/projects/" + projectId + "/plan", { method: "POST" })
                .then(function (res) {
                    if (!res.ok) {
                        return res.json().then(function (err) {
                            throw new Error(err.error || "Planning failed.");
                        });
                    }
                    return res.json();
                })
                .then(function () {
                    window.location.reload();
                })
                .catch(function (err) {
                    alert(err.message);
                    planBtn.disabled = false;
                    planBtn.textContent = "Trigger Planning";
                });
            });
        }
    });
})();
