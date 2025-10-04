from dataclasses import dataclass
from typing import Optional


@dataclass
class SensingContext:
    url: str = ""
    domContent: Optional[str] = None
    imageDescription: Optional[str] = None
