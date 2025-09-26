from flask import Flask, request, jsonify
import motor.motor_asyncio  # type: ignore
import os
import asyncio

from src.agent import run_agent
from src.eval import eval_group

app = Flask(__name__)

MONGO_DB_URI = os.getenv("MONGO_DB_URI")
if os.getenv("MONGODB_URI") is None and MONGO_DB_URI:
    os.environ["MONGODB_URI"] = MONGO_DB_URI

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_DB_URI)
db = client['ransomware_db']
victims_collection = db['victims']
session_collection = db['session']

@app.route('/run_agent', methods=['POST'])
def agent_endpoint():
    data = request.json or {}
    start_url = data.get('start_url')
    headless = bool(data.get('headless', True))
    model = data.get('model')
    max_steps = data.get('max_steps')
    if not start_url:
        return jsonify({"error": "Missing start_url"}), 400
    
    result = asyncio.run(
        run_agent(
            start_url,
            headless=headless,
            victims_collection=victims_collection,
            session_collection=session_collection,
            model=model,
            max_steps=max_steps
        )
    )
    return jsonify(result)

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