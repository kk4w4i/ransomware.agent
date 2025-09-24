from typing import Any, Dict, List, Optional
import json

def action_key_str(action: Dict[str, Any]) -> str:
    return json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def map_actions_to_results(
    actions: List[Dict[str, Any]],
    results: List[Optional[bool]],
    strict: bool = True,
) -> Dict[str, Optional[bool]]:
    if strict and len(actions) != len(results):
        raise ValueError(f"Length mismatch: actions={len(actions)} results={len(results)}")
    return {action_key_str(a): r for a, r in zip(actions, results)}