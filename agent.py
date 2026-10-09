
import json
import os

import requests
from pydantic import BaseModel, Field

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

class PlannedStep(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    tool: str
    depends_on: list[int] = Field(default_factory=list)

class EventPlan(BaseModel):
    event_name: str
    steps: list[PlannedStep] = Field(min_length=1, max_length=12)

ALLOWED_TOOLS = {"create_task", "get_weather", "list_tasks"}

def create_plan(request_text: str) -> dict:
    """Ask the local model to produce a structured event operations plan."""
    if not request_text.strip():
        return {"success": False, "error": "Please describe the event."}

    schema = EventPlan.model_json_schema()

    prompt = f"""
You are CampusOps AI, an operations planning assistant for college events.

USER REQUEST:
{request_text}

Create a practical plan containing 3 to 5 steps.

STRICT RULES:
1. Return only JSON matching the supplied schema.
2. The event_name must be a short, meaningful event name.
3. Every step must use exactly one of these tool names:
   - create_task
   - get_weather
   - list_tasks
4. Never use any other tool name.
5. For ordinary event preparation, use create_task.
6. Use get_weather only when weather information is relevant.
7. Use list_tasks only when existing tasks need to be inspected.
8. Each step must have a meaningful title and description.
9. Dependencies must refer only to earlier steps, using zero-based indices.
10. Do not claim that any task has already been executed.
11. Do not invent weather results or claim a booking has been confirmed.
12. If information is missing, create a preparation task to obtain it.

Return JSON matching this schema:
{json.dumps(schema)}
"""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": schema,
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        raw = payload.get("response", "")

        plan = EventPlan.model_validate_json(raw)

        for index, step in enumerate(plan.steps):
            if step.tool not in ALLOWED_TOOLS:
                return {
                    "success": False,
                    "error": f"Unsupported tool in step {index}: {step.tool}",
                }

            if any(dep < 0 or dep >= index for dep in step.depends_on):
                return {
                    "success": False,
                    "error": f"Invalid dependency in step {index}.",
                }

        return {
            "success": True,
            "model": MODEL_NAME,
            "event_name": plan.event_name,
            "steps": [step.model_dump() for step in plan.steps],
            "executed": False,
        }

    except requests.RequestException as exc:
        return {
            "success": False,
            "error": f"Could not connect to Ollama: {exc}",
        }
    except (ValueError, TypeError) as exc:
        return {
            "success": False,
            "error": f"The model returned an invalid plan: {exc}",
        }