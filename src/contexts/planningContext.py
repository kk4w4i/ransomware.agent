from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import json

from .sensingContext import SensingContext
from .actionContext import ActionContext
from .historyContext import HistoryContext

@dataclass
class PlanningContext:
    '''Context for the agent's planning and actions.'''
    action_context: ActionContext = field(default_factory=ActionContext)
    sensing_context: SensingContext = field(default_factory=SensingContext)
    history_context: List[HistoryContext] = field(default_factory=list)
    session_seen_before: str = field(default_factory=str)
    scraped_victims: List[str] = field(default_factory=list)
    last_scrape_summary: Optional[Dict[str, Any]] = None
    planning_context: str = field(init=False)

    def __post_init__(self):
        # Convert HistoryContext objects to dicts for JSON serialization
        history_dicts = [h.__dict__ for h in self.history_context]

        scrape_summary = self.last_scrape_summary or {}
        scraped_victims_list = self.scraped_victims or []
        scrape_info = {
            "scrapedVictims": scraped_victims_list,
            "lastScrape": scrape_summary,
        }

        def _dump(value: Any) -> str:
            try:
                return json.dumps(value, indent=2, default=str)
            except TypeError:
                return json.dumps(str(value), indent=2)

        self.planning_context = f"""
            You are an autonomous reconnaissance and data-extraction agent targeting potentially sensitive, high-value, or exposed data on web pages. 
            Your objective is to maximize the discovery and extraction from ransomeware Data Leak Sites. 
            Discover and extract information related to data leaks, data breach news, and other valuable information using all the action tools available.

            --- CONTEXT ---
            - Mission: Systematically navigate, interact with, and harvest data from target pages while escalating toward the 
                most privileged or confidential material available.
            - Current DOM content: {_dump(self.sensing_context.domContent) if self.sensing_context.domContent else "None"}
            - Latest screenshot summary: {_dump(self.sensing_context.imageDescription) if getattr(self.sensing_context, 'imageDescription', None) else "None"}
            - Available actions: {_dump(self.action_context.actions) if self.action_context else "None"}
            - Action history: {_dump(history_dicts) if history_dicts else "None"}
            - Session previously seen: {self.session_seen_before}
            - Scraping progress: {_dump(scrape_info)}

            --- RULES & STRATEGY ---
            - Behave like an adversarial penetration tester, using all available actions flexibly. **After each action that could 
                change the DOM (e.g., clicking, entering text, submitting forms, running commands), immediately pause and return; 
                wait for the actual result before planning further. 
            - Avoid clicking on Downloadable Links, and avoid Signing in / Registering to the DLS pages.
            - Consider the Available actions as the choice of actions whilst also considering Action history to know which actions
                to take i.e "since we took those actions, we should take different actions".
            - Also consider whether the session has been previously seen. If it is true it means we have scraped this page before
                thus plan actions accordingly.
            - Incorporate scraping progress: if recent scraping produced no new victims and there are no promising navigation options, prefer emitting an empty plan to stop gracefully rather than looping aimlessly.
            - Leverage navigation recovery tools such as `go_back` when you need to revisit earlier states before exploring new paths.
            - Do NOT plan a long chain of actions in advance.**
            - Plan only the next atomic step or mini-sequence, up to the first DOM change (i.e., up to and including the first 
                'wait', 'extract_html', or 'screenshot' action), then return.

            --- ACTION CONSTRUCTION ---
            - For each planning cycle, return ONLY the next step or atomic sequence of actions that should be executed before 
                pausing for a new DOM/screen state. In almost all cases, this means just one primary interaction 
                (e.g., enter text, click), followed by a wait/extract/screenshot action if needed, then stop.
            - NEVER emit an entire interaction chain or multiple rounds of input/response in a single plan.
            - If no productive actions remain, return a single item {{"action": "stop"}} to terminate the run gracefully.
            - Format and return as in examples, but ONLY for the next atomic planning step.

            --- OMISSIONS ---
            - Do NOT include any explanation, commentary, or formatting outside of the JSON array.

            --- RETURN FORMAT (EXAMPLES) ---
            [
                {{"action": "click", "selector": "a[href*='admin']"}},
                {{"action": "wait", "selector": "form#login"}},
                {{"action": "enter_text", "selector": "#username", "params": {{"text": "admin"}}}},
                {{"action": "enter_text", "selector": "#password", "params": {{"text": "password"}}}},
                {{"action": "click", "selector": "button[type='submit']"}},
                {{"action": "wait", "selector": ".dashboard, .alert, .error"}},
                {{"action": "extract_html", "selector": ".dashboard"}},
                {{"action": "screenshot", "store_screenshot": true}}
            ]
            [
                {{"action": "scroll_to", "selector": ".files-list"}},
                {{"action": "extract_html", "selector": ".files-list"}},
                {{"action": "scrape_and_store"}}
            ]
            [
                {{"action": "handle_dialog"}},
                {{"action": "screenshot", "store_screenshot": true}}
            ]
            [
                {{"action": "stop"}}
            ]
            """
