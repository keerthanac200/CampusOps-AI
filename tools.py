
import json
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
TASKS_FILE = BASE_DIR / "tasks.json"

def load_tasks():
    if not TASKS_FILE.exists():
        return []

    with TASKS_FILE.open("r", encoding="utf-8") as file:
        tasks = json.load(file)

    if not isinstance(tasks, list):
        raise ValueError("tasks.json must contain a list.")

    return tasks

def save_tasks(tasks):
    with TASKS_FILE.open("w", encoding="utf-8") as file:
        json.dump(tasks, file, indent=2)

def create_task(title, description="", depends_on=None):
    title = title.strip()

    if not title:
        return {
            "success": False,
            "error": "Task title cannot be empty."
        }

    try:
        tasks = load_tasks()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"success": False, "error": str(exc)}

    dependencies = depends_on or []
    existing_ids = {task["id"] for task in tasks}

    unknown = [
        task_id for task_id in dependencies
        if task_id not in existing_ids
    ]

    if unknown:
        return {
            "success": False,
            "error": "Unknown prerequisite task IDs.",
            "unknown_dependencies": unknown
        }

    number = 1
    while f"TASK-{number:03d}" in existing_ids:
        number += 1

    task = {
        "id": f"TASK-{number:03d}",
        "title": title,
        "description": description,
        "depends_on": dependencies,
        "status": "blocked" if dependencies else "pending"
    }

    tasks.append(task)

    try:
        save_tasks(tasks)
    except OSError as exc:
        return {"success": False, "error": str(exc)}

    return {"success": True, "task": task}

def list_tasks():
    try:
        tasks = load_tasks()
        return {
            "success": True,
            "count": len(tasks),
            "tasks": tasks
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"success": False, "error": str(exc)}

def complete_task(task_id):
    try:
        tasks = load_tasks()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"success": False, "error": str(exc)}

    task = next(
        (item for item in tasks if item["id"] == task_id),
        None
    )

    if task is None:
        return {
            "success": False,
            "error": f"Task {task_id} was not found."
        }

    incomplete = []

    for dependency_id in task.get("depends_on", []):
        dependency = next(
            (item for item in tasks if item["id"] == dependency_id),
            None
        )

        if dependency is None or dependency["status"] != "completed":
            incomplete.append(dependency_id)

    if incomplete:
        return {
            "success": False,
            "error": "Prerequisite tasks are not complete.",
            "blocked_by": incomplete
        }

    task["status"] = "completed"

    for candidate in tasks:
        if candidate["status"] == "blocked":
            dependencies = candidate.get("depends_on", [])

            if all(
                any(
                    item["id"] == dependency_id
                    and item["status"] == "completed"
                    for item in tasks
                )
                for dependency_id in dependencies
            ):
                candidate["status"] = "pending"

    try:
        save_tasks(tasks)
    except OSError as exc:
        return {"success": False, "error": str(exc)}

    return {"success": True, "task": task}

def get_weather(latitude, longitude):
    if not -90 <= latitude <= 90:
        return {"success": False, "error": "Invalid latitude."}

    if not -180 <= longitude <= 180:
        return {"success": False, "error": "Invalid longitude."}

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
        "timezone": "auto"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        return {
            "success": True,
            "current": data.get("current", {}),
            "source": "Open-Meteo"
        }

    except requests.RequestException as exc:
        return {
            "success": False,
            "error": f"Weather request failed: {exc}"
        }

AVAILABLE_TOOLS = {
    "create_task": create_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "get_weather": get_weather
}