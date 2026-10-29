"""회의실 현황 페이지 (CloudFront → Lambda Function URL)

GET /                         rooms.html
GET /api/rooms?date=YYYY-MM-DD 회의실, 그날 예약, 최근 MCP 호출, Gateway 상태
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

TZ = timezone(timedelta(hours=float(os.environ.get("TIMEZONE_OFFSET_HOURS", "9"))))
ddb = boto3.resource("dynamodb")
rooms_table = ddb.Table(os.environ["ROOMS_TABLE"])
bookings_table = ddb.Table(os.environ["BOOKINGS_TABLE"])
activity_table = ddb.Table(os.environ["ACTIVITY_TABLE"])
agentcore = boto3.client("bedrock-agentcore-control")

PAGE = (Path(__file__).parent / "rooms.html").read_text(encoding="utf-8")
_cache = {}


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _plain(obj):
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, set):
        return sorted(_plain(v) for v in obj)
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def _gateway_status():
    try:
        g = agentcore.get_gateway(gatewayIdentifier=os.environ["GATEWAY_ID"])
        return {"name": g["name"], "status": g["status"]}
    except Exception as e:  # noqa: BLE001
        return {"name": os.environ["GATEWAY_ID"], "status": f"ERROR: {e}"}


def _rooms():
    return sorted(_plain(rooms_table.scan().get("Items", [])), key=lambda r: (r["floor"], r["room_id"]))


def _bookings(rooms, date):
    out = []
    for r in rooms:
        resp = bookings_table.query(
            KeyConditionExpression=Key("room_id").eq(r["room_id"]) & Key("start_time").begins_with(date))
        out.extend(_plain(resp.get("Items", [])))
    return sorted(out, key=lambda b: (b["start_time"], b["room_id"]))


def _activity(limit=20):
    resp = activity_table.query(KeyConditionExpression=Key("pk").eq("activity#meeting-room"),
                                ScanIndexForward=False, Limit=limit)
    out = []
    for it in _plain(resp.get("Items", [])):
        ts = int(it["sk"].split("#")[0])
        try:
            args = json.loads(it.get("args") or "{}")
        except ValueError:
            args = {}
        out.append({"id": it["sk"], "time": datetime.fromtimestamp(ts / 1000, TZ).strftime("%H:%M:%S"),
                    "tool": it.get("tool"), "args": args, "ok": it.get("ok", True), "summary": it.get("summary")})
    return out


def rooms_state(qs):
    now = datetime.now(TZ)
    date = qs.get("date") or now.strftime("%Y-%m-%d")
    rooms = _cached("rooms", 300, _rooms)
    return {"now": now.isoformat(), "date": date,
            "tz_offset_hours": TZ.utcoffset(None).total_seconds() / 3600,
            "gateway": _cached("gateway", 30, _gateway_status),
            "rooms": rooms, "bookings": _bookings(rooms, date), "activity": _activity()}


def lambda_handler(event, context):
    path = event.get("rawPath", "/").rstrip("/") or "/"
    if path in ("/", "/index.html", "/rooms.html"):
        return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"},
                "body": PAGE}
    if path == "/api/rooms":
        body = rooms_state(event.get("queryStringParameters") or {})
        return {"statusCode": 200, "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
                "body": json.dumps(body, ensure_ascii=False, default=str)}
    return {"statusCode": 404, "headers": {"Content-Type": "application/json"}, "body": '{"error":"not found"}'}
