from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class HistoryContext:
    step: int
    actionsWithResults: List[Dict[str, Any]] = field(default_factory=list)
