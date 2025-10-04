from typing import Any, Dict, List, Optional

from src.contexts.planningContext import PlanningContext
from src.contexts.actionContext import ActionContext
from src.contexts.historyContext import HistoryContext
from src.managers.llm_manager import LLMManager

class PlanningManager:
    def __init__(self):
        self.historical_actions: List[HistoryContext] = []
        self.scraped_victims: List[str] = []
        self.last_scrape_summary: Optional[Dict[str, Any]] = None
        self.consecutive_noop_plans: int = 0

    async def build_context(
        self, 
        browser_manager, 
        session_seen_before
    ) -> PlanningContext:
        sensing_context = browser_manager.sensingcontext
        action_context = ActionContext()
        history_contexts = self.historical_actions

        # Pass seen_before into PlanningContext, e.g. use stored_content or add a new field
        context = PlanningContext(
            action_context=action_context,
            sensing_context=sensing_context,
            history_context=history_contexts,
            session_seen_before=['seen_before:' + str(session_seen_before)],  # Simple way to inject into prompt
            scraped_victims=self.scraped_victims,
            last_scrape_summary=self.last_scrape_summary,
        )
        
        return context
    
    async def plan(
        self, 
        context: PlanningContext,
        llm: LLMManager
    ):
        plan = await llm.get_llm_plan(str(context.planning_context))
        return plan

    def update_history(self, step: int, actions_with_results: List[Dict[str, Any]]) -> None:
        filtered_actions = []

        for item in actions_with_results:
            action = item.get("action", {})
            results = item.get("results", {})
            payload = results.get("payload")

            if action.get("name") == "scrape_and_store":
                victim_names = []
                if isinstance(payload, dict):
                    victim_names = payload.get("victimNames") or []
                    total_entries = payload.get("totalEntries")
                else:
                    total_entries = None

                if victim_names:
                    for name in victim_names:
                        if name and name not in self.scraped_victims:
                            self.scraped_victims.append(name)
                self.last_scrape_summary = {
                    "victims": victim_names,
                    "totalEntries": total_entries,
                    "timestampStep": step,
                }

                filtered_actions.append(
                    {
                        "action": action,
                        "results": {
                            "status": results.get("status"),
                            "message": results.get("message"),
                            "victimNames": victim_names,
                            "totalEntries": total_entries,
                        },
                    }
                )
            else:
                filtered_actions.append(item)

        history = HistoryContext(step=step, actionsWithResults=filtered_actions)
        self.historical_actions.append(history)

    def register_plan(self, planned_actions: List[Dict[str, Any]]) -> bool:
        should_stop = False
        if planned_actions:
            for action in planned_actions:
                if isinstance(action, dict):
                    if str(action.get("action", "")).lower() == "stop" or action.get("stop") is True:
                        should_stop = True
                        break
            if should_stop:
                self.consecutive_noop_plans += 1
            else:
                self.consecutive_noop_plans = 0
        else:
            self.consecutive_noop_plans += 1
        return should_stop

    def should_stop(self) -> bool:
        if self.consecutive_noop_plans >= 2:
            return True
        if self.consecutive_noop_plans >= 1:
            last_total = None
            if self.last_scrape_summary:
                last_total = self.last_scrape_summary.get("totalEntries")
            if last_total in (0, None):
                return True
        return False
