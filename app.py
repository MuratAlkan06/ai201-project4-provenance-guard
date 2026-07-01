"""
app.py — Provenance Guard API.

Endpoints:
  POST /submit  { text, creator_id }            -> classify, label, log
  POST /appeal  { content_id, creator_reasoning } -> flip status, log appeal
  GET  /log                                      -> recent audit-log entries
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

import detection
import audit_log

app = Flask(__name__)

# Rate limiting: 10/min accommodates a real writer publishing a batch while blocking
# rapid-fire flooding; 100/day caps sustained scripted abuse. Keyed by IP because there is
# no auth in this prototype (see README limitations).
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

audit_log.init_db()


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = body.get("creator_id") or "anonymous"

    if not text:
        return jsonify({"error": "field 'text' is required"}), 400

    result = detection.score_text(text)
    content_id = str(uuid.uuid4())
    audit_log.record_submission(content_id, creator_id, text, result)

    return jsonify({
        "content_id": content_id,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "label": result["label"],
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = body.get("content_id")
    creator_reasoning = (body.get("creator_reasoning") or "").strip()

    if not content_id or not creator_reasoning:
        return jsonify({
            "error": "fields 'content_id' and 'creator_reasoning' are required"
        }), 400

    ok = audit_log.record_appeal(content_id, creator_reasoning)
    if not ok:
        return jsonify({"error": f"unknown content_id: {content_id}"}), 404

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal received. This content's status is now under review.",
    })


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": audit_log.get_recent_log()})


if __name__ == "__main__":
    app.run(port=5000, debug=True)
