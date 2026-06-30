#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from urllib import request


SYSTEM_PROMPT = """你是一个谨慎的交易复核助手。只根据用户提供的行情、持仓和规则做短线监控复核。
输出必须是严格 JSON，不要 Markdown。
原则：
1. 不能要求脚本自动下单，只能建议通知用户。
2. 只有当新规则明显降低误报、漏报或风险时才更新规则。
3. 规则更新必须给出具体数值和理由。
4. 不要编造外部行情；如果信息不足，返回不更新。
"""


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("empty payload")
    return json.loads(raw)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response did not contain JSON")
    return json.loads(text[start : end + 1])


def _chat(payload: dict) -> str:
    api_key = os.environ.get("VIBETRADING_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set VIBETRADING_API_KEY or OPENAI_API_KEY to enable LLM review.")

    base_url = os.environ.get("VIBETRADING_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model = (
        payload.get("preferred_model")
        or os.environ.get("VIBETRADING_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "gpt-4o-mini"
    )
    url = base_url.rstrip("/") + "/chat/completions"

    user_prompt = {
        "task": "盘中关键节点复核。判断是否需要通知用户，以及是否需要更新后续通知规则。",
        "required_schema": {
            "notify": "boolean",
            "notification_title": "string, notify=true 时必填",
            "notification_body": "string, notify=true 时必填，必须说明更新理由",
            "rule_updates": "object, key 为允许更新的规则名，value 为数字；无更新则 {}",
            "update_reason": "string, 说明为什么更新或为什么不更新",
            "analysis": "string, 简短行情判断",
        },
        "payload": payload,
    }
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=int(os.environ.get("VIBETRADING_TIMEOUT", "45"))) as resp:
        response = json.loads(resp.read().decode("utf-8", "ignore"))
    return response["choices"][0]["message"]["content"]


def main() -> int:
    payload = _read_payload()
    result = _extract_json(_chat(payload))
    if isinstance(result, dict) and payload.get("preferred_model"):
        result["_model_used"] = payload["preferred_model"]
        result["_review_tier"] = payload.get("review_tier", "standard")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
