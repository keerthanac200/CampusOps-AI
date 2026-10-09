from tools import create_task, get_weather, list_tasks

AVAILABLE_TOOLS = {
    "create_task": create_task,
    "get_weather": get_weather,
    "list_tasks": list_tasks,
}


def execute_plan(plan: dict) -> dict:
    """Execute the supported operations in a validated AI plan."""

    if not isinstance(plan, dict):
        return {
            "success": False,
            "error": "Invalid plan format.",
            "results": [],
        }

    steps = plan.get("steps")

    if not isinstance(steps, list):
        return {
            "success": False,
            "error": "Plan must contain a list of steps.",
            "results": [],
        }

    results = []

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            results.append({
                "step": index,
                "success": False,
                "error": "Invalid step format.",
            })
            continue

        tool_name = step.get("tool")

        if tool_name not in AVAILABLE_TOOLS:
            results.append({
                "step": index,
                "success": False,
                "error": f"Unsupported tool: {tool_name}",
            })
            continue

        # Never execute an action unless its prerequisites succeeded.
        dependencies = step.get("depends_on", [])

        if not isinstance(dependencies, list) or any(
            not isinstance(dep, int)
            or isinstance(dep, bool)
            or dep < 0
            or dep >= index
            for dep in dependencies
        ):
            results.append({
                "step": index,
                "success": False,
                "error": "Invalid dependency references.",
            })
            continue

        if any(
            dependencies
            and not any(
                result["step"] == dep and result["success"]
                for result in results
            )
            for dep in dependencies
        ):
            results.append({
                "step": index,
                "success": False,
                "error": "A prerequisite step did not succeed.",
            })
            continue

        # Tool arguments must be explicit and validated.
        arguments = step.get("arguments", {})

        if not isinstance(arguments, dict):
            results.append({
                "step": index,
                "success": False,
                "error": "Tool arguments must be an object.",
            })
            continue

        try:
            if tool_name == "create_task":
                title = step.get("title", "")
                description = step.get("description", "")
                task_dependencies = arguments.get("depends_on", [])

                if not isinstance(title, str) or not title.strip():
                    raise ValueError("Task title is required.")

                if not isinstance(description, str):
                    raise ValueError("Task description must be text.")

                if not isinstance(task_dependencies, list):
                    raise ValueError("Task dependencies must be a list.")

                result = create_task(
                    title=title,
                    description=description,
                    depends_on=task_dependencies,
                )

            elif tool_name == "get_weather":
                latitude = arguments.get("latitude")
                longitude = arguments.get("longitude")

                if (
                    not isinstance(latitude, (int, float))
                    or isinstance(latitude, bool)
                    or not -90 <= latitude <= 90
                    or not isinstance(longitude, (int, float))
                    or isinstance(longitude, bool)
                    or not -180 <= longitude <= 180
                ):
                    raise ValueError(
                        "Valid latitude and longitude are required."
                    )

                result = get_weather(latitude, longitude)

            else:
                result = list_tasks()

            # Tool-level failure must not be reported as success.
            tool_success = (
                isinstance(result, dict)
                and result.get("success") is True
            )

            results.append({
                "step": index,
                "tool": tool_name,
                "success": tool_success,
                "result": result,
            })

        except Exception as exc:
            results.append({
                "step": index,
                "tool": tool_name,
                "success": False,
                "error": str(exc),
            })

    all_succeeded = bool(results) and all(
        item["success"] for item in results
    )

    return {
        "success": all_succeeded,
        "executed": True,
        "total_steps": len(results),
        "successful_steps": sum(
            item["success"] for item in results
        ),
        "failed_steps": sum(
            not item["success"] for item in results
        ),
        "results": results,
    }