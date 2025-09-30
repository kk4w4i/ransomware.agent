from flask import Flask, request, jsonify
from flask_cors import CORS
import motor.motor_asyncio  # type: ignore
import os
import asyncio
import threading
from typing import Optional

from src.agent import run_agent
from src.eval import eval_group
from src.managers.stream_manager import StreamManager

app = Flask(__name__)

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

_agent_control: dict[str, Optional[object]] = {
    "thread": None,
    "stop_event": None,
}

@app.route('/run_agent', methods=['POST'])
def agent_endpoint():
    data = request.json or {}
    start_url = data.get('start_url')
    headless = bool(data.get('headless', False))
    model = data.get('model', 'deepseek-chat')
    max_steps = data.get('max_steps', 50)
    if not start_url:
        return jsonify({"error": "Missing start_url"}), 400
    stream_manager = StreamManager.get_instance()

    existing_thread = _agent_control.get("thread")
    if isinstance(existing_thread, threading.Thread) and existing_thread.is_alive():
        return jsonify({"error": "Agent already running"}), 409

    ready_timeout = float(os.getenv("AGENT_READY_TIMEOUT", "30"))
    ready_event = threading.Event()
    state: dict[str, object] = {"status": "starting"}
    stop_event = threading.Event()
    _agent_control["stop_event"] = stop_event

    def on_ready() -> None:
        state["status"] = "ready"
        ready_event.set()

    def runner() -> None:
        try:
            result = asyncio.run(
                run_agent(
                    start_url,
                    headless=headless,
                    victims_collection=victims_collection,
                    session_collection=session_collection,
                    model=model,
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
            _agent_control["thread"] = None
            _agent_control["stop_event"] = None

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    _agent_control["thread"] = thread

    ready_event.wait(timeout=ready_timeout)

    status = state.get("status", "starting")
    if status == "error":
        return jsonify({"status": "error", "error": state.get("error")}), 500

    if status == "ready":
        return jsonify({"status": "started", "stream": stream_manager.info()}), 200

    return jsonify({"status": status}), 202


@app.route('/stream/info', methods=['GET'])
def stream_info():
    manager = StreamManager.get_instance()
    return jsonify(manager.info())


@app.route('/run_agent/stop', methods=['POST'])
def stop_agent():
    thread = _agent_control.get("thread")
    stop_event = _agent_control.get("stop_event")

    if not isinstance(thread, threading.Thread) or not thread.is_alive() or not isinstance(stop_event, threading.Event):
        return jsonify({"status": "idle"}), 200

    stop_event.set()
    return jsonify({"status": "stopping"}), 200

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

if __name__ == "__main__":
    app.run(debug=True, port=5001)
