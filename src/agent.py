import ast
import hashlib
import os
from threading import Event
from typing import Callable, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from src.managers.browser_manager import BrowserManager
from src.managers.llm_manager import LLMManager
from src.managers.planning_manager import PlanningManager
from src.managers.stream_manager import StreamManager
from src.utils.map_actions_to_results import map_actions_to_results
from src.utils.text_utils import clean_text

async def run_agent(
        start_url: str,
        model: str,
        job_id: str,
        headless: bool = True,
        victims_collection=None,
        session_collection=None,
        max_steps: int = 50,
        on_ready: Optional[Callable[[], None]] = None,
        stop_signal: Optional[Event] = None,
    ):
    stream_manager = StreamManager.get_instance()
    await stream_manager.ensure_server()
    bm = None
    mongo_client: Optional[AsyncIOMotorClient] = None
    final_status_payload: Optional[dict] = None
    try:
        if victims_collection is None or session_collection is None:
            mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGO_DB_URI")
            if not mongo_uri:
                raise RuntimeError("MongoDB connection URI not configured")
            db_name = os.getenv("MONGO_DB_NAME", "ransomware_db")
            mongo_client = AsyncIOMotorClient(mongo_uri)
            db = mongo_client[db_name]
            victims_collection = db['victims']
            session_collection = db['session']

        print(f"Starting at: {start_url}")
        print("Starting agent...")

        llm = LLMManager(model=model)
        print(f"Using model: {llm.model} with context window: {llm.context_size}")

        bm = BrowserManager(
            start_url,
            job_id=job_id,
            headless=True,
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
                    job_id,
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
                job_id,
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
                pm.update_history(steps, mapped_action_result)
                await stream_manager.push_event(
                    job_id,
                    "execution",
                    {
                        "step": steps,
                        "actions": mapped_action_result,
                    },
                )
            except Exception as e:
                print(f"Action execution failed: {e}")
                await stream_manager.push_event(
                    job_id,
                    "execution_error",
                    {
                        "step": steps,
                        "error": str(e),
                    },
                )
                break

        print("Agent finished.")
        if stop_signal and stop_signal.is_set():
            final_status = "stopped"
        else:
            final_status = "complete"
        final_status_payload = {
            "status": final_status,
            "stepsRan": steps,
        }
        return {"status": final_status, "steps_ran": steps}
    except Exception as e:
        final_status_payload = {
            "status": "failed",
            "error": str(e),
        }
        print(f"Agent Fail with {e}")
    finally:
        if bm is not None:
            try:
                await bm.exit()
            except Exception as exit_error:  # pylint: disable=broad-except
                print(f"Error during browser manager shutdown: {exit_error}")
        if final_status_payload is not None:
            try:
                await stream_manager.push_event(job_id, "agent_status", final_status_payload)
            except Exception as event_error:  # pylint: disable=broad-except
                print(f"Failed to push final status event: {event_error}")
        if mongo_client is not None:
            mongo_client.close()
