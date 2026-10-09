
import copy
from agent import validate_plan


valid_plan = {
    "goal": "Organize a coding workshop",
    "tasks": [
            {
            "id": "T1",
            "title": "Review event requirements",
            "tool": "create_task",
            "depends_on": [],
            "priority": "high",
            "inputs": {
                "title": "Review event requirements",
                "priority": "high",
                "description": "Review the workshop requirements"
            }
        }
    ]
}

def should_reject(name, plan):
    try:
        validate_plan(plan)
        print(f"FAIL: {name} was accepted")
    except ValueError:
        print(f"PASS: {name} was rejected")


# Valid plan should pass.
validate_plan(valid_plan)
print("PASS: Valid plan accepted")

# Duplicate IDs should fail.

# Test: Duplicate task IDs must be rejected

# Test: Duplicate task IDs must be rejected
bad = copy.deepcopy(valid_plan)

duplicate_task = copy.deepcopy(bad["tasks"][0])
duplicate_task["id"] = bad["tasks"][0]["id"]
bad["tasks"].append(duplicate_task)

try:
    validate_plan(bad)
    print("FAIL: Duplicate task IDs were accepted")
except ValueError:
    print("PASS: Duplicate task IDs were rejected")
# Unregistered tools should fail.
bad = copy.deepcopy(valid_plan)
bad["tasks"][0]["tool"] = "delete_everything"
should_reject("Unregistered tool", bad)

# Circular dependencies should fail.
bad = copy.deepcopy(valid_plan)
bad["tasks"][0]["depends_on"] = ["T2"]
should_reject("Circular dependencies", bad)

# Unknown dependencies should fail.

# Test: Unknown dependency must be rejected
bad = copy.deepcopy(valid_plan)
bad["tasks"][0]["depends_on"] = ["T99"]

try:
    validate_plan(bad)
    print("FAIL: Unknown dependency was accepted")
except ValueError:
    print("PASS: Unknown dependency was rejected")