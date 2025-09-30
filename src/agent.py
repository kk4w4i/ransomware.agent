from src.managers.browser_manager import BrowserManager
from src.managers.planning_manager import PlanningManager
from src.managers.llm_manager import LLMManager
from src.managers.stream_manager import StreamManager
import ast
from src.utils.text_utils import clean_text
import hashlib
from src.utils.map_actions_to_results import map_actions_to_results
from typing import Callable, Optional
from threading import Event
from typing import Callable, Optional

async def run_agent(
        start_url: str,
        model: str,
        headless: bool = False,
        victims_collection=None,
        session_collection=None,
        max_steps: int = 50,
        on_ready: Optional[Callable[[], None]] = None,
        stop_signal: Optional[Event] = None,
    ):
    stream_manager = StreamManager.get_instance()
    await stream_manager.ensure_server()
    bm = None
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
        if on_ready:
            try:
                on_ready()
            except Exception as callback_exc:  # pylint: disable=broad-except
                print(f"on_ready callback errored: {callback_exc}")

        pm = PlanningManager()

        steps = 0
        while steps < max_steps:
            if stop_signal and stop_signal.is_set():
                print("Stop signal received before sensing; exiting loop.")
                break
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
            sensing_context = bm.sensingcontext
            if sensing_context:
                await stream_manager.push_event(
                    "sensing",
                    {
                        "step": steps,
                        "url": sensing_context.url,
                        "summary": sensing_context.domContent,
                        "seenBefore": seen_before,
                    },
                )
            
            # --- Create the context ---
            context = await pm.build_context(bm, session_seen_before=seen_before)

            #####################################################
            #                       PLAN                        #
            #####################################################
            if stop_signal and stop_signal.is_set():
                print("Stop signal received before planning; exiting loop.")
                break
            print(f"\nStep {steps}: Now planning actions...")
            plan = await pm.plan(context, llm)
            print(f"\nStep {steps}: Planned actions: {plan}")
            await stream_manager.push_event(
                "planning",
                {
                    "step": steps,
                    "plan": plan,
                },
            )
            if not plan:
                print("No more actions planned. Stopping agent loop.")
                break

            #####################################################
            #                       EXECUTE                     #
            #####################################################
            if stop_signal and stop_signal.is_set():
                print("Stop signal received before execution; exiting loop.")
                break
            try:
                if isinstance(plan, str):
                    plan = ast.literal_eval(plan)
                actions = plan if isinstance(plan, list) else []
                print(actions)
                results = await bm.execute(actions)

                mapped_action_result = map_actions_to_results(actions, results, strict=True)

                # Add the actions to the history context
                pm.update_history(bm._page.url, mapped_action_result)
                await stream_manager.push_event(
                    "execution",
                    {
                        "step": steps,
                        "actions": actions,
                        "results": results,
                        "mappedResults": mapped_action_result,
                    },
                )
            except Exception as e:
                print(f"Action execution failed: {e}")
                await stream_manager.push_event(
                    "execution_error",
                    {
                        "step": steps,
                        "error": str(e),
                    },
                )
                break

        await bm.exit()
        print("Agent finished.")
        if stop_signal and stop_signal.is_set():
            final_status = "stopped"
        else:
            final_status = "complete"
        await stream_manager.push_event(
            "agent_status",
            {
                "status": final_status,
                "stepsRan": steps,
            },
        )
        return {"status": final_status, "steps_ran": steps}
    except Exception as e:
        await stream_manager.push_event(
            "agent_status",
            {
                "status": "failed",
                "error": str(e),
            },
        )
        if bm is not None:
            await bm.exit()
        print(f"Agent Fail with {e}")
