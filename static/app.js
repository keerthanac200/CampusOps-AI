
const API_BASE = ""; // Same-origin API; FastAPI should serve this frontend.

const $ = (id) => document.getElementById(id);

let currentRunId = null;
let currentTasks = [];
let currentWeather = null;

function logActivity(title, detail, isError = false) {
  const entry = document.createElement("p");
  entry.className = "log-entry";

  const dot = document.createElement("span");
  dot.className = "log-dot";
  if (isError) dot.style.background = "#ff9caa";

  const content = document.createElement("span");
  const strong = document.createElement("strong");
  strong.textContent = title;

  const small = document.createElement("small");
  small.textContent = detail;

  content.append(strong, small);

  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit"
  });

  entry.append(dot, content, time);
  $("activity-log").prepend(entry);
}

function setMessage(message, type = "") {
  $("form-message").textContent = message;
  $("form-message").className = `message ${type}`;
}

function getTasks(data) {
  const candidates = [
    data?.tasks,
    data?.steps,
    data?.plan?.tasks,
    data?.plan?.steps,
    data?.result?.tasks,
    data?.result?.steps
  ];

  return candidates.find(Array.isArray) || [];
}

function getTaskStatus(task) {
  const status = String(task.status || "pending").toLowerCase();

  if (["done", "success", "completed", "complete"].includes(status)) {
    return "completed";
  }
  if (["error", "failed", "failure"].includes(status)) return "failed";
  if (["blocked", "waiting"].includes(status)) return "blocked";
  if (["running", "in_progress", "executing"].includes(status)) return "running";

  return "pending";
}

function renderTasks(tasks) {
  currentTasks = tasks;
  $("task-list").replaceChildren();

  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";

    const icon = document.createElement("span");
    icon.textContent = "✳";

    const heading = document.createElement("strong");
    heading.textContent = "No tasks returned";

    const description = document.createElement("p");
    description.textContent =
      "The backend returned no tasks. Check the planner response.";

    empty.append(icon, heading, description);
    $("task-list").append(empty);
  } else {
    tasks.forEach((task, index) => {
      const card = document.createElement("article");
      card.className = "task-card";

      const top = document.createElement("div");
      top.className = "task-top";

      const title = document.createElement("div");
      title.className = "task-title";
      title.textContent =
        task.title || task.name || task.task || `Task ${index + 1}`;

      const badge = document.createElement("span");
      const status = getTaskStatus(task);
      badge.className = `task-badge ${status}`;
      badge.textContent = status.replace("_", " ").toUpperCase();

      top.append(title, badge);

      const description = document.createElement("p");
      description.className = "task-description";
      description.textContent =
        task.description || task.details || "No description supplied.";

      const meta = document.createElement("div");
      meta.className = "task-meta";

      const priority = document.createElement("span");
      priority.className = "task-badge";
      priority.textContent = `Priority: ${task.priority || "Normal"}`;
      meta.append(priority);

      const dependencies = task.dependencies || task.depends_on;
      if (Array.isArray(dependencies) && dependencies.length) {
        const dependencyBadge = document.createElement("span");
        dependencyBadge.className = "task-badge";
        dependencyBadge.textContent =
          `Depends on: ${dependencies.join(", ")}`;
        meta.append(dependencyBadge);
      }

      if (task.requires_approval || task.approval_required) {
        const approval = document.createElement("span");
        approval.className = "task-badge pending";
        approval.textContent = "Approval required";
        meta.append(approval);
      }

      card.append(top, description, meta);
      $("task-list").append(card);
    });
  }

  $("task-count").textContent = tasks.length;
  $("task-tag").textContent = `${tasks.length} TASK${tasks.length === 1 ? "" : "S"}`;
  updateStats();
}

function updateStats() {
  const completed = currentTasks.filter(
    (task) => getTaskStatus(task) === "completed"
  ).length;

  const attention = currentTasks.filter((task) =>
    ["failed", "blocked"].includes(getTaskStatus(task))
  ).length;

  $("completed-count").textContent = completed;
  $("attention-count").textContent = attention;
}

function renderWeather(data) {
  const weather =
    data?.weather ||
    data?.plan?.weather ||
    data?.context?.weather ||
    data?.result?.weather;

  if (!weather) return;

  currentWeather = weather;

  if (typeof weather === "string") {
    $("weather-summary").textContent = weather;
    $("weather-detail").textContent =
      "Weather information returned by the backend.";
    return;
  }

  $("weather-summary").textContent =
    weather.summary || weather.condition || weather.description ||
    "Weather data received";

  const details = [
    weather.location,
    weather.temperature != null ? `${weather.temperature}°` : null,
    weather.precipitation_probability != null
      ? `${weather.precipitation_probability}% precipitation chance`
      : null
  ].filter(Boolean);

  $("weather-detail").textContent =
    details.join(" · ") || "Weather information returned by the agent.";
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  const text = await response.text();
  let data = {};

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    throw new Error(
      data.detail || data.message || `Request failed (${response.status})`
    );
  }

  return data;
}

async function checkBackend() {
  try {
    await apiRequest("/api/health");
    $("connection-label").textContent = "Backend connected";
    $("connection-label").style.color = "#62d6a5";
    logActivity("Backend connected", "Health check succeeded.");
  } catch (error) {
    $("connection-label").textContent = "Backend unavailable";
    $("connection-label").style.color = "#ff9caa";
    logActivity(
      "Backend unavailable",
      "Start the FastAPI server before submitting requests.",
      true
    );
  }
}

$("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const request = $("event-request").value.trim();
  if (!request) {
    setMessage("Please describe the event first.", "error");
    return;
  }

  const button = $("plan-button");
  button.disabled = true;
  button.textContent = "Planning…";
  $("approve-button").disabled = false;
  $("approval-area").hidden = true;
  setMessage("Sending your request to the AI planner…");

  $("workflow-status").textContent = "Planning";
  currentRunId = null;
  currentTasks = [];
  currentWeather = null;
  renderTasks([]);

  logActivity("Planning requested", request);

  try {
    const data = await apiRequest("/api/plan", {
      method: "POST",
      body: JSON.stringify({ request })
    });

    currentRunId = data.run_id || data.runId || data.id || null;

    const tasks = getTasks(data);
    renderTasks(tasks);
    renderWeather(data);

    $("workflow-status").textContent = "Plan created";

    if (currentRunId) {
      $("approval-area").hidden = false;
      setMessage("Plan received. Review the tasks before approving execution.", "success");
    } else {
      setMessage(
        "Plan response received, but no run_id was returned. Ask the backend developer to include run_id.",
        "error"
      );
    }

    logActivity(
      "Plan received",
      `${tasks.length} task(s) returned by the backend.`
    );
  } catch (error) {
    $("workflow-status").textContent = "Plan failed";
    setMessage(
      `Could not generate the plan: ${error.message}. Check that FastAPI and Ollama are running.`,
      "error"
    );
    logActivity("Planning failed", error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "✳ Generate plan";
  }
});

$("approve-button").addEventListener("click", async () => {
  if (!currentRunId) {
    setMessage("No valid run ID is available. Generate a plan first.", "error");
    return;
  }

  const button = $("approve-button");
  button.disabled = true;
  button.textContent = "Executing…";
  $("workflow-status").textContent = "Executing";
  setMessage("Submitting approval and starting execution…");

  logActivity("Approval submitted", `Run ID: ${currentRunId}`);

  try {
    await apiRequest("/api/approve", {
      method: "POST",
      body: JSON.stringify({
        run_id: currentRunId,
        approved: true
      })
    });

    const result = await apiRequest("/api/execute", {
      method: "POST",
      body: JSON.stringify({ run_id: currentRunId })
    });

    const tasks = getTasks(result);
    if (tasks.length) renderTasks(tasks);
    renderWeather(result);

    const status = String(result.status || "Execution response received");
    $("workflow-status").textContent = status;

    setMessage(
      "Execution response received. Check task statuses and the activity log.",
      "success"
    );
    logActivity("Execution response", status);
  } catch (error) {
    $("workflow-status").textContent = "Execution error";
    setMessage(
      `Execution could not be confirmed: ${error.message}. Check the backend logs before retrying.`,
      "error"
    );
    logActivity("Execution error", error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Approve & execute";
  }
});

$("clear-log").addEventListener("click", () => {
  $("activity-log").replaceChildren();
  logActivity("Activity view cleared", "New activity will appear here.");
});

checkBackend();