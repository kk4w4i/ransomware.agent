import uuid
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import motor.motor_asyncio  # type: ignore
import os
import asyncio
import threading
from typing import Dict


from src.agent import run_agent
from src.eval import eval_group
from src.managers.stream_manager import StreamManager
from src.managers.vector_store_manager import VectorStoreManager

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me")

raw_origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
CORS(
    app,
    resources={
        r"/*": {
            "origins": allowed_origins,
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    },
    supports_credentials=True,
)

MONGO_DB_URI = os.getenv("MONGO_DB_URI")
if os.getenv("MONGODB_URI") is None and MONGO_DB_URI:
    os.environ["MONGODB_URI"] = MONGO_DB_URI

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_DB_URI)
db = client['ransomware_db']
victims_collection = db['victims']
session_collection = db['session']

_agent_control: Dict[str, Dict[str, object]] = {}

@app.route('/run_agent', methods=['POST'])
def agent_endpoint():
    data = request.json or {}
    start_url = data.get('start_url')
    model = data.get('model', 'deepseek-chat')
    max_steps = data.get('max_steps', 50)
    if not start_url:
        return jsonify({"error": "Missing start_url"}), 400
    stream_manager = StreamManager.get_instance()
    headless = bool(data.get('headless', True))
    job_id = str(uuid.uuid4())
    ready_timeout = float(os.getenv("AGENT_READY_TIMEOUT", "30"))
    ready_event = threading.Event()
    stop_event = threading.Event()
    state: Dict[str, object] = {"status": "starting"}
    _agent_control[job_id] = {
        "thread": None,
        "stop_event": stop_event,
        "state": state,
    }

    jobs = session.get("jobs", [])
    jobs.append(job_id)
    session["jobs"] = jobs[-10:]
    session["current_job_id"] = job_id
    session.modified = True

    def on_ready() -> None:
        state["status"] = "ready"
        ready_event.set()

    def runner() -> None:
        try:
            result = asyncio.run(
                run_agent(
                    start_url=start_url,
                    model=model,
                    job_id=job_id,
                    headless=headless,
                    max_steps=max_steps,
                    on_ready=on_ready,
                    stop_signal=stop_event,
                )
            )
            final_status = result.get("status") if isinstance(result, dict) else None
            if not ready_event.is_set():
                state["status"] = final_status or "complete"
                ready_event.set()
        except Exception as exc:  # pylint: disable=broad-except
            state["status"] = "error"
            state["error"] = str(exc)
            if not ready_event.is_set():
                ready_event.set()
        finally:
            _agent_control.pop(job_id, None)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    _agent_control[job_id]["thread"] = thread

    ready_event.wait(timeout=ready_timeout)

    status = state.get("status", "starting")
    if status == "error":
        return jsonify({"status": "error", "error": state.get("error"), "jobId": job_id}), 500

    if status == "ready":
        return jsonify({"status": "started", "jobId": job_id, "stream": stream_manager.info(job_id)}), 200

    return jsonify({"status": status, "jobId": job_id}), 202


@app.route('/stream/info', methods=['GET'])
def stream_info():
    job_id = request.args.get('jobId') or session.get("current_job_id")
    manager = StreamManager.get_instance()
    return jsonify(manager.info(job_id))


@app.route('/run_agent/stop', methods=['POST'])
def stop_agent():
    data = request.get_json(silent=True) or {}
    job_id = data.get('jobId') or session.get("current_job_id")
    if not job_id:
        return jsonify({"error": "Missing jobId"}), 400

    entry = _agent_control.get(job_id)
    if not entry:
        return jsonify({"status": "idle", "jobId": job_id}), 200

    stop_event = entry.get("stop_event")
    thread = entry.get("thread")

    if not isinstance(stop_event, threading.Event) or not isinstance(thread, threading.Thread):
        return jsonify({"status": "idle", "jobId": job_id}), 200

    stop_event.set()

    jobs = [jid for jid in session.get("jobs", []) if jid != job_id]
    session["jobs"] = jobs
    if session.get("current_job_id") == job_id:
        session["current_job_id"] = jobs[-1] if jobs else None
    session.modified = True

    return jsonify({"status": "stopping", "jobId": job_id}), 200

@app.route("/eval_extraction", methods=["POST"])
def eval_extraction_endpoint():
    data = request.get_json(silent=True) or {}
    required = [
        "groupName"
    ]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        result = asyncio.run(
            eval_group(
                group_name=data["groupName"],
                live_db_name="ransomware-live",
                agent_db_name="ransomware_db",
                live_coll_name="victims",
                agent_coll_name="victims",
                fields=data.get("fields"),
            )
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route('/groups', methods=['GET'])
def groups_endpoint():
    async def get_groups():
        groups = await victims_collection.distinct("ransomwareGroup")
        return groups

    groups = asyncio.run(get_groups())
    return jsonify({"groups": groups}), 200

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200


@app.route('/victims/deduplicate', methods=['POST'])
def dedupe_victims():
    data = request.get_json(silent=True) or {}
    threshold = float(data.get('threshold', 0.85))
    search_limit = int(data.get('searchLimit', 25))

    async def run_dedupe():
        async with VectorStoreManager() as manager:
            result = await manager.deduplicate_collection(
                victims_collection,
                threshold=threshold,
                search_limit=search_limit,
            )
            return result

    try:
        result = asyncio.run(run_dedupe())
        return jsonify(result), 200
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5001)
