
import json
import os
import requests


# ==========================================
# 1. CONFIGURATION
# ==========================================

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat"
)

MODEL = os.getenv(
    "OLLAMA_MODEL",
    "gemma3:4b"
)

ALLOWED_TOOLS = {
    "create_task",
    "list_tasks",
    "update_task_status",
    "verify_task",
    "get_weather",
}

TOOL_DESCRIPTIONS = {
    "create_task": (
        "Create one task. Required: title. "
        "Optional: priority and description."
    ),
    "list_tasks": "Retrieve all saved tasks. No inputs required.",
    "update_task_status": (
        "Update a task. Required: task_id and status."
    ),
    "verify_task": "Verify a task. Required: task_id.",
    "get_weather": (
        "Fetch current weather. Required: latitude and longitude."
    ),
}


# ==========================================
# 2. AI PLANNER PROMPT
# ==========================================

PLANNER_PROMPT = """
You are CampusOps AI, an AI assistant for college event operations.

Convert the user's request into a practical task plan.

Return ONLY valid JSON in this format:

{
  "goal": "Organize a college event",
  "tasks": [
    {
      "id": "T1",
      "title": "Create event task",
      "tool": "create_task",
      "depends_on": [],
      "priority": "high",
      "inputs": {
        "title": "Review event requirements",
        "priority": "high",
        "description": "Review the event requirements"
      }
    }
  ]
}

Rules:
- Generate 3 to 8 tasks.
- Use only the registered tools provided.
- Every task ID must be unique.
- Dependencies must refer to existing task IDs.
- Dependencies must not contain cycles.
- Priority must be high, medium, or low.
- Every task must have an inputs object.
- create_task requires title; priority and description are optional.
- list_tasks requires an empty inputs object.
- update_task_status requires task_id and status.
- verify_task requires task_id.
- get_weather requires numeric latitude and longitude.
- Never invent weather results or claim that a tool ran.
- Never invent coordinates.
- Do not mark tasks completed merely because they were planned.
- Do not create tasks that send messages or make bookings.
- Return JSON only, without Markdown code fences.
"""


# ==========================================
# 3. GENERATE A PLAN WITH OLLAMA
# ==========================================

def create_plan(user_request: str) -> dict:
    """Generate and validate a plan using the local Ollama model."""

    if not isinstance(user_request, str):
        raise ValueError("Request must be text.")

    user_request = user_request.strip()

    if not 5 <= len(user_request) <= 1000:
        raise ValueError(
            "Request must contain between 5 and 1000 characters."
        )

    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": PLANNER_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"User goal: {user_request}\n\n"
                    f"Registered tools: "
                    f"{json.dumps(TOOL_DESCRIPTIONS)}"
                ),
            },
        ],
        "options": {
            "temperature": 0,
        },
    }

    print("Connecting to Ollama...", flush=True)
    print("Waiting for the model to generate a plan...", flush=True)

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(10, 180),
        )
        response.raise_for_status()

        result = response.json()
        content = result["message"]["content"]
        plan = json.loads(content)

    except requests.Timeout as exc:
        raise RuntimeError(
            "Ollama took too long to respond. Try again."
        ) from exc

    except requests.RequestException as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. Check that it is running "
            "and that the model is installed."
        ) from exc

    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Ollama returned invalid JSON or an unexpected response."
        ) from exc

    return validate_plan(plan)


# ==========================================
# 4. VALIDATE TOOL INPUTS
# ==========================================

def validate_tool_inputs(task: dict) -> dict:
    """Validate inputs against Supriya's shared tool signatures."""

    if not isinstance(task, dict):
        raise ValueError("Task must be an object.")

    tool = task.get("tool")
    inputs = task.get("inputs")

    if tool not in ALLOWED_TOOLS:
        raise ValueError(f"Unknown tool: {tool}")

    if not isinstance(inputs, dict):
        raise ValueError("Tool inputs must be a JSON object.")

    required_fields = {
        "create_task": {"title"},
        "list_tasks": set(),
        "update_task_status": {"task_id", "status"},
        "verify_task": {"task_id"},
        "get_weather": {"latitude", "longitude"},
    }

    missing = required_fields[tool] - inputs.keys()

    if missing:
        raise ValueError(
            f"{tool} is missing required inputs: "
            f"{', '.join(sorted(missing))}"
        )

    if tool == "create_task":
        title = inputs["title"]

        if not isinstance(title, str) or not title.strip():
            raise ValueError("Task title must be non-empty text.")

        priority = inputs.get("priority", "medium")

        if (
            not isinstance(priority, str)
            or priority.strip().lower() not in {"low", "medium", "high"}
        ):
            raise ValueError("Priority must be low, medium, or high.")

        description = inputs.get("description", "")

        if not isinstance(description, str):
            raise ValueError("Description must be text.")

    if tool in {"verify_task", "update_task_status"}:
        task_id = inputs["task_id"]

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be non-empty text.")

    if tool == "update_task_status":
        if inputs["status"] not in {
            "pending",
            "in_progress",
            "completed",
            "blocked",
        }:
            raise ValueError("Invalid task status.")

    if tool == "get_weather":
        for field, minimum, maximum in (
            ("latitude", -90, 90),
            ("longitude", -180, 180),
        ):
            value = inputs[field]

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not minimum <= value <= maximum
            ):
                raise ValueError(f"Invalid {field}.")

    for key, value in inputs.items():
        if value is None or value == "":
            raise ValueError(f"Input '{key}' cannot be empty.")

    return task


# ==========================================
# 5. VALIDATE THE COMPLETE PLAN
# ==========================================

def validate_plan(plan: dict) -> dict:
    """Validate task fields, tools, dependencies, and cycles."""

    if not isinstance(plan, dict):
        raise ValueError("Plan must be a JSON object.")

    goal = plan.get("goal")
    tasks = plan.get("tasks")

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Plan needs a non-empty goal.")

    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Plan must contain at least one task.")

    if len(tasks) > 12:
        raise ValueError("Plan cannot contain more than 12 tasks.")

    ids = set()

    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Every task must be an object.")

        task_id = task.get("id")

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Every task needs a valid ID.")

        if task_id in ids:
            raise ValueError(f"Duplicate task ID: {task_id}")

        ids.add(task_id)

        title = task.get("title")

        if not isinstance(title, str) or not title.strip():
            raise ValueError(
                f"Task {task_id} needs a non-empty title."
            )

        if task.get("tool") not in ALLOWED_TOOLS:
            raise ValueError(
                f"Task {task_id} requests an unapproved tool."
            )

        if task.get("priority") not in {"high", "medium", "low"}:
            raise ValueError(
                f"Task {task_id} has invalid priority."
            )

        dependencies = task.get("depends_on")

        if not isinstance(dependencies, list):
            raise ValueError(
                f"Task {task_id} has invalid dependencies."
            )

        if not all(
            isinstance(dep, str) and dep.strip()
            for dep in dependencies
        ):
            raise ValueError(
                f"Task {task_id} has invalid dependency IDs."
            )

        if len(dependencies) != len(set(dependencies)):
            raise ValueError(
                f"Task {task_id} has duplicate dependencies."
            )

        validate_tool_inputs(task)

    graph = {
        task["id"]: task["depends_on"]
        for task in tasks
    }

    for task in tasks:
        for dependency in task["depends_on"]:
            if dependency not in ids:
                raise ValueError(
                    f"Task {task['id']} depends on unknown task "
                    f"{dependency}."
                )

            if dependency == task["id"]:
                raise ValueError(
                    f"Task {task['id']} cannot depend on itself."
                )

    visiting = set()
    visited = set()

    def visit(task_id):
        if task_id in visiting:
            raise ValueError("Circular dependency detected.")

        if task_id in visited:
            return

        visiting.add(task_id)

        for dependency in graph[task_id]:
            visit(dependency)

        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)

    return plan


# ==========================================
# 6. RUN THE PLANNER
# ==========================================

if __name__ == "__main__":

    sample_request = (
        "Organize a college coding workshop for 60 students "
        "in Bengaluru. Create event tasks and review the plan."
    )

    print(f"Using Ollama model: {MODEL}", flush=True)

    try:
        plan = create_plan(sample_request)

        print("\nAI-GENERATED PLAN")
        print("=" * 40)
        print(json.dumps(plan, indent=2))

        print("\nPlanner validation successful.")

    except (ValueError, RuntimeError) as error:
        print(f"\nPlanner failed: {error}")