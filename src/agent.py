from src.managers.browser_manager import BrowserManager
from src.managers.planning_manager import PlanningManager
from src.managers.llm_manager import LLMManager
import ast
from src.utils.text_utils import clean_text
import hashlib
from src.utils.map_actions_to_results import map_actions_to_results

async def run_agent(
        start_url: str,
        model: str,
        headless: bool = True,
        victims_collection=None,
        session_collection=None,
        max_steps: int = 20
    ):
    try:
        print(f"Starting at: {start_url}")
        print("Starting agent...")

        llm = LLMManager(model=model)
        print(f"Using model: {llm.model} with context window: {llm.context_size}")

        bm = BrowserManager(
            start_url,
            headless=headless,
            victims_collection=victims_collection,
            session_collection=session_collection,
            llm=llm
        )
        await bm.start()

        pm = PlanningManager()

        steps = 0
        while steps < max_steps:
            steps += 1

            #####################################################
            #                       SENSE                       #
            #####################################################
            print(f"\nStep {steps}: Sensing current state of the browser...")
            await bm.sense()

            # --- Check session before planning ---
            page = bm._page
            full_text = await page.content()
            full_text = await clean_text(full_text)
            url = str(page.url)
            text_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
            existing = await session_collection.find_one({'url': url, 'text_hash': text_hash})
            seen_before = bool(existing)
            print(f"\nSession seen before: {seen_before}")
            
            # --- Create the context ---
            context = await pm.build_context(bm, session_seen_before=seen_before)

            #####################################################
            #                       PLAN                        #
            #####################################################    
            print(f"\nStep {steps}: Now planning actions...")
            plan = await pm.plan(context, llm)
            print(f"\nStep {steps}: Planned actions: {plan}")
            if not plan:
                print("No more actions planned. Stopping agent loop.")
                break

            #####################################################
            #                       EXECUTE                     #
            #####################################################
            try:
                if isinstance(plan, str):
                    plan = ast.literal_eval(plan)
                actions = plan if isinstance(plan, list) else []
                print(actions)
                results = await bm.execute(actions)

                mapped_action_result = map_actions_to_results(actions, results, strict=True)

                # Add the actions to the history context
                pm.update_history(bm._page.url, mapped_action_result)
            except Exception as e:
                print(f"Action execution failed: {e}")
                break

        await bm.exit()
        print("Agent finished.")
        return {"status": "complete", "steps_ran": steps}
    except Exception as e:
        await bm.exit()
        print(f"Agent Fail with {e}")


