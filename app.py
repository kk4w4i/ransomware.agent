from flask import Flask, request, jsonify
import motor.motor_asyncio
import os

from src.agent import run_agent

app = Flask(__name__)

# --- MongoDB Initialization at app start ---
MONGO_DB_URI = os.getenv("MONGO_DB_URI")
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_DB_URI)
db = client['ransomware_db']
victims_collection = db['victims']
session_collection = db['session']

@app.route('/run_agent', methods=['POST'])
def agent_endpoint():
    data = request.json
    start_url = data.get('start_url')
    headless = bool(data.get('headless', True))
    model = data.get('model')
    max_steps = data.get('max_steps')
    if not start_url:
        return jsonify({"error": "Missing start_url"}), 400
    # Pass MongoDB handles to your agent
    import asyncio
    result = asyncio.run(run_agent(start_url, headless=headless,
                                   victims_collection=victims_collection,
                                   session_collection=session_collection,
                                   model=model,
                                   max_steps=max_steps))
    return jsonify(result)

@app.route('/test_suite', methods=['POST'])
def test_suite_endpoint():
    data = request.json
    test_suite = data.get('test_suite')
    headless = bool(data.get('headless', True))
    model = data.get('model')
    max_steps = data.get('max_steps')
    if not test_suite or not isinstance(test_suite, list):
        return jsonify({"error": "Missing or invalid test_suite"}), 400
    results = []
    import asyncio
    for test in test_suite:
        start_url = test.get('start_url')
        if not start_url:
            results.append({"error": "Missing start_url in one of the tests"})
            continue
        result = asyncio.run(run_agent(start_url, headless=headless,
                                       victims_collection=victims_collection,
                                       session_collection=session_collection,
                                       model=model,
                                       max_steps=max_steps))
        results.append(result)
    return jsonify(results)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5001)