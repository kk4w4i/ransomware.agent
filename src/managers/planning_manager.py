from src.contexts.planningContext import PlanningContext
from src.contexts.actionContext import ActionContext
from src.contexts.historyContext import HistoryContext
from src.managers.llm_manager import LLMManager

class PlanningManager:
    def __init__(self):
        self.historical_actions = []

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
            session_seen_before=['seen_before:' + str(session_seen_before)]  # Simple way to inject into prompt
        )
        
        return context
    
    async def plan(
        self, 
        context: PlanningContext,
        llm: LLMManager
    ):
        plan = await llm.get_llm_plan(str(context.planning_context))
        return plan

    def update_history(self, url: str, actions: list):
        for action in actions:
            history = HistoryContext(url, action)
            self.historical_actions.append(history)