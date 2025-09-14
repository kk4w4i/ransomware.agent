from dataclasses import dataclass

@dataclass
class HistoryContext:
    locationURL: str = ""
    action: str = ""