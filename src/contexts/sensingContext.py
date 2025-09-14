from dataclasses import dataclass
@dataclass
class SensingContext:
    url: str = ""
    imgDescription: str = None
    domContent: str = None