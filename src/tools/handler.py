"""회의실 예약 MCP 도구 (AgentCore Gateway Lambda target)

도구 5개: list_rooms, check_availability, book_room, cancel_booking, my_schedule
Gateway는 도구 이름을 context.client_context.custom["bedrockAgentCoreToolName"]에
"<target>___<tool>" 형태로 넘기고, event에는 도구 인자만 담아 보낸다.
"""
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

ddb = boto3.resource("dynamodb")
rooms_table = ddb.Table(os.environ["ROOMS_TABLE"])
bookings_table = ddb.Table(os.environ["BOOKINGS_TABLE"])
activity_table = ddb.Table(os.environ["ACTIVITY_TABLE"])

GATEWAY = "meeting-room"


def _plain(obj):
    """DynamoDB Decimal/set 을 JSON 으로 내보낼 수 있게 바꾼다."""
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, set):
        return sorted(_plain(v) for v in obj)
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def list_rooms():
    items = _plain(rooms_table.scan().get("Items", []))
    return sorted(items, key=lambda r: r["room_id"])


def check_availability(room_id, date):
    resp = bookings_table.query(
        KeyConditionExpression=Key("room_id").eq(room_id) & Key("start_time").begins_with(date)
    )
    bookings = _plain(resp.get("Items", []))
    return {"room_id": room_id, "date": date, "bookings": bookings, "count": len(bookings)}


def book_room(room_id, date, start_hour, duration_minutes, booked_by, title):
    start_time = f"{date}T{int(start_hour):02d}:00"
    end_time = (datetime.fromisoformat(start_time) + timedelta(minutes=int(duration_minutes))).strftime("%Y-%m-%dT%H:%M")

    if not rooms_table.get_item(Key={"room_id": room_id}).get("Item"):
        return {"success": False, "error": f"없는 회의실입니다: {room_id}. list_rooms 로 회의실 ID를 확인하세요."}

    existing = bookings_table.query(
        KeyConditionExpression=Key("room_id").eq(room_id) & Key("start_time").begins_with(date)
    ).get("Items", [])
    for b in existing:
        if b["start_time"] < end_time and b["end_time"] > start_time:
            return {"success": False, "error": f"시간 충돌: {b['title']} ({b['start_time']}~{b['end_time']})"}

    item = {"room_id": room_id, "start_time": start_time, "end_time": end_time,
            "booked_by": booked_by, "title": title}
    bookings_table.put_item(Item=item)
    return {"success": True, "booking": item}


def cancel_booking(room_id, start_time):
    bookings_table.delete_item(Key={"room_id": room_id, "start_time": start_time})
    return {"success": True, "cancelled": {"room_id": room_id, "start_time": start_time}}


def my_schedule(name, date):
    resp = bookings_table.scan(
        FilterExpression=Attr("booked_by").eq(name) & Attr("start_time").begins_with(date)
    )
    return _plain(resp.get("Items", []))


TOOLS = {
    "list_rooms": list_rooms,
    "check_availability": check_availability,
    "book_room": book_room,
    "cancel_booking": cancel_booking,
    "my_schedule": my_schedule,
}


def _summary(tool, result):
    if tool == "list_rooms":
        return f"회의실 {len(result)}개 조회"
    if tool == "check_availability":
        return f"{result['room_id']} {result['date']} 예약 {result['count']}건"
    if tool == "book_room":
        if result.get("success"):
            b = result["booking"]
            return f"{b['room_id']} {b['start_time']}~{b['end_time'][11:]} 예약 완료 ({b['booked_by']})"
        return f"예약 실패: {result.get('error')}"
    if tool == "cancel_booking":
        c = result["cancelled"]
        return f"{c['room_id']} {c['start_time']} 예약 취소"
    if tool == "my_schedule":
        return f"예약 {len(result)}건 조회"
    return ""


def _log(tool, args, ok, summary, started):
    """대시보드에 보여줄 호출 기록. 실패해도 도구 응답에는 영향을 주지 않는다."""
    try:
        now = time.time()
        activity_table.put_item(Item={
            "pk": f"activity#{GATEWAY}",
            "sk": f"{int(now * 1000)}#{uuid.uuid4().hex[:8]}",
            "gateway": GATEWAY,
            "tool": tool,
            "args": json.dumps(args, ensure_ascii=False)[:1000],
            "ok": ok,
            "summary": summary[:500],
            "latency_ms": int((now - started) * 1000),
            "ttl": int(now) + 7 * 24 * 3600,
        })
    except Exception as e:  # noqa: BLE001
        print(f"activity log failed: {e}")


def lambda_handler(event, context):
    started = time.time()
    full_name = (context.client_context.custom or {}).get("bedrockAgentCoreToolName", "") if context.client_context else ""
    tool = full_name.split("___", 1)[-1]
    args = event if isinstance(event, dict) else {}
    print(json.dumps({"tool": full_name, "args": args}, ensure_ascii=False))

    fn = TOOLS.get(tool)
    if not fn:
        return {"error": f"unknown tool: {full_name}"}
    try:
        result = fn(**args)
        ok = not (isinstance(result, dict) and result.get("success") is False)
        _log(tool, args, ok, _summary(tool, result), started)
        return result
    except Exception as e:  # noqa: BLE001
        _log(tool, args, False, f"오류: {e}", started)
        return {"error": str(e)}
