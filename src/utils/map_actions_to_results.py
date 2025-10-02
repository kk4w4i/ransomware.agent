from typing import Any, Dict, List


def map_actions_to_results(
    actions: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    strict: bool = True,
) -> List[Dict[str, Any]]:
    if strict and len(actions) != len(results):
        raise ValueError(f"Length mismatch: actions={len(actions)} results={len(results)}")

    mapped: List[Dict[str, Any]] = []
    for action, outcome in zip(actions, results):
        outcome = outcome or {}
        status = outcome.get("status", "unknown")
        message = outcome.get("message", "")
        mapped.append(
            {
                "action": {
                    "name": action.get("action"),
                    "selector": action.get("selector"),
                    "params": action.get("params", {}) or {},
                },
                "results": {
                    "status": status,
                    "message": message,
                },
            }
        )
    return mapped
