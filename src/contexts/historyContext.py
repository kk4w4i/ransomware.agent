from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class HistoryContext:
    locationURL: str = ""
    action_mapped_results: Dict[str, Optional[bool]] = None