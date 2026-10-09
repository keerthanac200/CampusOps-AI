from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import create_plan
from executor import execute_plan
from venue_routes import router as venue_router

app = FastAPI(
    title="CampusOps AI",
    description="AI-powered college operations planning and task management.",
    version="1.0.0",
)
app.include_router(venue_router)

# Temporary in-memory storage for demonstration.
# Runs will be lost when the server restarts.
runs = {}


class PlanRequest(BaseModel):
    request: str = Field(min_length=5, max_length=2000)


class ApprovalRequest(BaseModel):
    approved: bool


@app.get("/")
def home():
    return {
        "success": True,
        "message": "Welcome to CampusOps AI",
        "status": "running",
        "documentation": "/docs",
    }


@app.get("/api/health")
def health():
    return {
        "success": True,
        "service": "CampusOps AI",
        "backend": "FastAPI",
        "ai_model": "Ollama",
        "status": "healthy",
    }


@app.post("/api/plan")
def generate_plan(data: PlanRequest):
    result = create_plan(data.request)

    if not isinstance(result, dict) or not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result,
        )

    run_id = str(uuid4())

    runs[run_id] = {
        "run_id": run_id,
        "request": data.request,
        "plan": result,
        "status": "awaiting_approval",
        "execution": None,
    }

    return {
        "success": True,
        "run_id": run_id,
        "status": "awaiting_approval",
        "message": "Review the plan before approving execution.",
        "plan": result,
    }


@app.post("/api/approve/{run_id}")
def approve_plan(run_id: str, data: ApprovalRequest):
    run = runs.get(run_id)

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Run not found.",
        )

    if run["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Run cannot be approved in status: {run['status']}",
        )

    if not data.approved:
        run["status"] = "rejected"

        return {
            "success": True,
            "run_id": run_id,
            "status": "rejected",
            "message": "The plan was rejected. No tools were executed.",
        }

    run["status"] = "executing"

    execution = execute_plan(run["plan"])
    run["execution"] = execution

    if execution.get("success"):
        run["status"] = "completed"
    else:
        run["status"] = "failed"

    return {
        "success": execution.get("success", False),
        "run_id": run_id,
        "status": run["status"],
        "execution": execution,
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = runs.get(run_id)

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Run not found.",
        )

    return run