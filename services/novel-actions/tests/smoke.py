#!/usr/bin/env python3
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, token=None, method="GET", body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, json.loads(raw) if "json" in content_type else raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, exc.headers.get("Content-Type", ""), json.loads(raw)


def data(result):
    status, _, payload = result
    assert status == 200, payload
    assert payload["ok"] is True, payload
    return payload["data"]


def assert_actionable(snapshot):
    action = snapshot["next_action"]
    if action["type"] in {"completed", "await_user_review", "request_human_review"}:
        assert action.get("action") is None and action.get("payload_schema") is None
    else:
        assert isinstance(action.get("action"), str) and action["action"]
        assert isinstance(action.get("payload_schema"), dict)
    return action


def workflow(base, token, action, book_id, payload):
    return data(request(base, "/v1/actions/novel", token, "POST", {
        "action": action, "book_id": book_id, "payload": payload,
    }))


def contract_payload(start, end, revision_batch_id=None):
    plans = []
    for no in range(start, end + 1):
        plans.append({
            "chapter_no": no, "title_intent": f"第{no}章推进",
            "protagonist_goal": f"主角主动完成第{no}章目标", "obstacle": f"第{no}章现实阻力",
            "consequential_choice": f"主角作出不可撤销选择{no}", "cost": f"承担真实代价{no}",
            "state_change": f"关系和局势发生变化{no}", "emotional_payoff": f"获得差异化情绪回报{no}",
            "type_promise": f"兑现作品类型承诺{no}", "conflict_engine": f"独立冲突引擎{no}",
            "ending_hook": f"留下因果钩子{no}", "structural_fingerprint": f"目标-选择-代价-变化-{no}",
        })
    payload = {"from": start, "to": end, "contract": {
        "protagonist": "林小满", "genre_promises": ["重生改变命运", "亲情修复", "成长逆袭"],
        "segment_goal": f"完成第{start}至{end}章连续推进",
        "prohibited_loops": ["发现漏洞后登记", "围观者集体夸赞", "重复解释规则"],
        "prior_segment_comparison": "本段逐章更换现实冲突来源、关键人物选择、实际代价和情绪回报，与最近章节的解决路径均不相同。",
        "chapter_plans": plans,
    }}
    if revision_batch_id:
        payload["revision_batch_id"] = revision_batch_id
    return payload


def checkpoint_state(last_chapter, current_chapter, formal_chapters=None):
    numbers = sorted(set(formal_chapters or list(range(1, last_chapter + 1))) | {current_chapter})
    return {
        "context": "这是完整上下文追踪，保留此前发生的关键事件、人物选择、冲突后果和未解决问题。" * 4,
        "characters": "林小满主动推动事件，其他人物各有目标、立场与变化。" * 4,
        "timeline": "\n".join(f"第{no:03d}章：记录本章时间推进和因果结果。" for no in numbers),
        "foreshadowing": "保留既有伏笔，并记录新伏笔的触发条件、回收期限和相关人物。" * 2,
        "chapter_index": "\n".join(f"第{no:03d}章：测试章节摘要。" for no in numbers),
        "structured": {"last_chapter": last_chapter, "characters": ["林小满"], "facts": ["连续性事实"]},
    }


def checkpoint_patch(chapter_no):
    return {
        "context_update": f"第{chapter_no:03d}章中主角作出主动选择并承担真实代价，人物关系和后续冲突因此发生可追踪变化。",
        "characters_update": f"第{chapter_no:03d}章后林小满的行动边界和关系状态发生变化，其他人物保留独立目标。",
        "timeline_entry": f"本章承接前序事件，冲突发生后由主角选择推动结果，并留下下一章可继续的因果。",
        "foreshadowing_update": f"本章推进既有关系伏笔，并记录后续需要通过人物行动回收的条件。",
        "chapter_index_entry": f"主角完成第{chapter_no:03d}章关键选择并承担结果。",
        "structured": {"characters_add": [f"第{chapter_no:03d}章人物状态"],
                       "facts_add": [f"第{chapter_no:03d}章连续性事实"]},
    }


def self_review(body):
    return {
        "protagonist_drives_plot": True, "genre_promise_delivered": True,
        "emotional_change_present": True, "no_repeated_loop": True, "ai_style_revised": True,
        "notes": "初稿存在动作和情绪连接偏弱的问题，已经补入主角主动选择、真实代价及关系变化，并清理模板化解释句。",
        "evidence": {"protagonist_action": body[:8], "emotional_change": body[20:28], "type_promise": body[40:48]},
    }


def review_candidate(base, token, book_id, chapter_no, contract_id, title, body, summary,
                     revision_batch_id=""):
    common = {"book_id": book_id}
    saved = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": "candidate_save", "payload_json": json.dumps({
            "contract_id": contract_id, "revision_batch_id": revision_batch_id,
            "chapter": {"chapter_no": chapter_no, "title": title, "body": body, "summary": summary},
        }, ensure_ascii=False),
    }))
    assert assert_actionable(saved)["type"] == "critique_chapter"
    assert saved["next_action"]["action"] == "candidate_critique"
    resume_action = "revision_get" if revision_batch_id else "writing_resume"
    resume = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": resume_action,
        "payload_json": json.dumps({"revision_batch_id": revision_batch_id} if revision_batch_id else {}),
    }))
    assert saved["next_action"] == resume["next_action"]
    assert resume["next_action"]["action"] == "candidate_critique"
    actor_template = resume["next_action"]["payload_schema"]["critique"]["scene_model"]["actors"][0]
    assert set(actor_template) == {"name", "age_role", "location", "action", "knowledge"}
    invalid = request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": "candidate_critique", "payload_json": json.dumps({
            "chapter_no": chapter_no, "revision_batch_id": revision_batch_id,
            "critique": {"scene_model": {
                "actors": [{"name": "林小满"}, {"name": "老师"}], "timeline": ["开始", "结束"],
                "props": [], "physical_and_social_constraints": "年代校园中的儿童行动受到成年人职责、现场距离、天气和安全规则共同限制，不能脱离现实条件。",
            }, "issues": []},
        }, ensure_ascii=False),
    })
    assert invalid[0] == 400 and "missing_fields" in invalid[2].get("details", {})
    scene_model = {
        "actors": [
            {"name": "林小满", "age_role": "六岁主角", "location": "教室", "action": "主动选择",
             "knowledge": "知道当前目标和风险"},
            {"name": "老师", "age_role": "成年教师", "location": "教室", "action": "履行保护职责",
             "knowledge": "知道学生年龄与现场限制"},
        ],
        "timeline": ["上课前确认目标和人物位置", "冲突后由主角承担代价并改变关系"],
        "props": [{"item": "课本", "count": "若干", "owner": "林小满", "transitions": "始终在教室"}],
        "physical_and_social_constraints": "故事发生在年代校园，六岁儿童不能越过教师职责独自处理危险，行动距离和时间必须符合现实。",
    }
    critique = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": "candidate_critique", "payload_json": json.dumps({
            "chapter_no": chapter_no, "revision_batch_id": revision_batch_id,
            "critique": {"scene_model": scene_model, "issues": [
                {"id": "logic-1", "severity": "medium", "category": "causality",
                 "evidence": body[:8], "reasoning": "初稿的主角动作与成年人职责连接不足，读者可能无法判断选择为何在当时环境中合理成立。",
                 "proposed_fix": "补入成年人职责和主角行动边界，让主动选择在现实约束下成立。"},
                {"id": "emotion-1", "severity": "low", "category": "emotion",
                 "evidence": body[20:28], "reasoning": "初稿情绪变化存在但动作落点偏少，需要通过人物可见反应强化而不是再增加解释总结。",
                 "proposed_fix": "增加一个具体动作结果，并删除一处直接解释情绪的句子。"},
            ]}
        }, ensure_ascii=False),
    }))
    assert assert_actionable(critique)["type"] == "revise_candidate"
    assert critique["next_action"]["action"] == "candidate_revise"
    resume = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": resume_action,
        "payload_json": json.dumps({"revision_batch_id": revision_batch_id} if revision_batch_id else {}),
    }))
    assert critique["next_action"] == resume["next_action"]
    assert resume["next_action"]["type"] == "revise_candidate"
    assert resume["next_action"]["action"] == "candidate_revise"
    assert set(resume["next_action"]["payload_schema"]) >= {
        "chapter_no", "revision_batch_id", "body", "changes",
    }
    revised = body + "\n\n林小满看见老师始终守在门边，才按约定向前一步；她承担选择的后果，关系也因此发生了真实变化。"
    revision = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": "candidate_revise", "payload_json": json.dumps({
            "chapter_no": chapter_no, "revision_batch_id": revision_batch_id, "body": revised,
            "changes": [
                {"issue_id": "logic-1", "revision": "补入老师始终在门边履行保护职责，并让主角只在约定边界内行动。"},
                {"issue_id": "emotion-1", "revision": "补入主角承担后果后关系发生变化的可见动作结果。"},
            ],
        }, ensure_ascii=False),
    }))
    assert assert_actionable(revision)["type"] == "verify_candidate"
    assert revision["next_action"]["action"] == "candidate_verify"
    resume = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": resume_action,
        "payload_json": json.dumps({"revision_batch_id": revision_batch_id} if revision_batch_id else {}),
    }))
    assert revision["next_action"] == resume["next_action"]
    assert resume["next_action"]["type"] == "verify_candidate"
    assert resume["next_action"]["action"] == "candidate_verify"
    assert set(resume["next_action"]["payload_schema"]["verification"]["checks"]) == {
        "causality_coherent", "character_motivation_coherent", "age_and_ability_plausible",
        "authority_and_duty_plausible", "time_and_space_consistent", "people_and_props_consistent",
        "emotional_change_earned", "genre_promise_delivered", "prose_not_expository",
    }
    check_evidence = revised[:8]
    verified = workflow(base, token, "candidate_verify", book_id, {
            "chapter_no": chapter_no, "revision_batch_id": revision_batch_id,
            "verification": {"scene_model": scene_model, "checks": {
                key: {"passed": True, "evidence": check_evidence,
                      "reasoning": "重新对照返修正文和场景模型进行因果推演，该项约束能由人物动作与现场结果共同支持。"}
                for key in (
                    "causality_coherent", "character_motivation_coherent", "age_and_ability_plausible",
                    "authority_and_duty_plausible", "time_and_space_consistent", "people_and_props_consistent",
                    "emotional_change_earned", "genre_promise_delivered", "prose_not_expository",
                )
            }, "residual_issues": [],
                "notes": "重新以陌生读者视角检查返修稿，成年人职责、儿童行动边界、时间位置、物件数量和情绪变化均能从正文动作中得到支持，未发现新矛盾。"}
        })
    assert verified["passed"] is True
    assert assert_actionable(verified)["type"] == "commit_verified_chapter"
    assert verified["next_action"]["action"] == "checkpoint_commit"
    resume = data(request(base, "/v1/actions/novel", token, "POST", {
        **common, "action": resume_action,
        "payload_json": json.dumps({"revision_batch_id": revision_batch_id} if revision_batch_id else {}),
    }))
    assert verified["next_action"] == resume["next_action"]
    assert resume["next_action"]["type"] == "commit_verified_chapter"
    assert resume["next_action"]["action"] == "checkpoint_commit"
    assert resume["next_action"]["payload_schema"]["contract_id"] == contract_id
    assert "state_patch" in resume["next_action"]["payload_schema"]
    return revised


def main():
    with tempfile.TemporaryDirectory(prefix="novel-actions-") as temp:
        root = Path(temp)
        state = root / "state"
        txt = root / "txt"
        state.mkdir()
        txt.mkdir()
        token = "smoke-test-token"
        (state / "action.token").write_text(token, encoding="utf-8")
        port = free_port()
        env = os.environ.copy()
        env.update({
            "NOVEL_ACTIONS_STATE_ROOT": str(state),
            "NOVEL_ACTIONS_TXT_ROOT": str(txt),
            "NOVEL_ACTIONS_PORT": str(port),
        })
        process = subprocess.Popen(
            [sys.executable, str(SERVICE_ROOT / "server.py")],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(50):
                try:
                    if request(base, "/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("service did not start")

            assert request(base, "/v1/defaults")[0] == 401
            assert request(base, "/openapi.json")[0] == 200
            unified_status, _, unified_spec = request(base, "/openapi-gpt.json")
            assert unified_status == 200
            unified_operations = [
                operation["operationId"] for path_item in unified_spec["paths"].values()
                for operation in path_item.values() if isinstance(operation, dict) and operation.get("operationId")
            ]
            assert sorted(unified_operations) == sorted([
                "runNovelWorkflow", "runFanqieWorkflow", "getNovelJob", "saveNovelAssets",
            ])
            assert len(json.dumps(unified_spec, ensure_ascii=False, separators=(",", ":"))) < 8000
            novel_schema = unified_spec["paths"]["/v1/actions/novel"]["post"]["requestBody"]["content"]["application/json"]["schema"]
            assert novel_schema["required"] == ["action", "payload"]
            assert novel_schema["properties"]["payload"]["type"] == "object"
            unified_defaults = data(request(base, "/v1/actions/novel", token, "POST", {
                "action": "defaults", "payload": {},
            }))
            assert unified_defaults["quality_profile"]["maximum_short_paragraph_ratio"] == 0.60
            bad_payload = request(base, "/v1/actions/novel", token, "POST", {
                "action": "book_find", "payload_json": "{bad",
            })
            assert bad_payload[0] == 400 and "payload_json" in bad_payload[2]["error"]
            privacy = request(base, "/privacy")
            assert privacy[0] == 200 and privacy[1].startswith("text/html")

            legacy_dir = txt / "重生六岁测试旧书"
            (legacy_dir / "正文").mkdir(parents=True)
            (legacy_dir / "追踪").mkdir(parents=True)
            (legacy_dir / "正文/第001章_旧书开端.md").write_text("旧" * 2600, encoding="utf-8")
            (legacy_dir / "正文/第002章_旧事重来.md").write_text("事" * 2600, encoding="utf-8")
            (legacy_dir / "作品信息_番茄上传.md").write_text(
                "书名：重生六岁测试旧书\n作者账号：桃枝醒醒\n番茄作品ID：7654615479075490878\n",
                encoding="utf-8",
            )
            legacy_query = urllib.parse.urlencode({"title": "六岁测试旧书"})
            legacy_found = data(request(base, f"/v1/books?{legacy_query}", token))
            assert legacy_found["resolved"] is True
            assert legacy_found["selected"]["registration_required"] is True
            legacy = data(request(base, "/v1/books/import-existing", token, "POST", {
                "title": "重生六岁测试旧书",
            }))
            assert legacy["imported"] is True and legacy["imported_chapters"] == 2
            assert legacy["next_chapter"] == 3 and legacy["account"] == "account-b"

            scores = {
                "originality": 20, "emotional_fit": 18, "opening_hook": 12,
                "serialization": 12, "heroine_agency": 8,
                "romantic_chemistry": 8, "fanqie_fit": 4, "total": 82,
            }
            candidates = [{
                "number": i, "working_title": f"候选{i}", "hook": f"钩子{i}",
                "emotional_promise": "稳定情绪回报", "heroine_engine": "女主主动推动剧情",
                "relationship_engine": "双向选择递进", "serialization_engine": "至少五个差异化单元",
                "risk": "避免单元同质化", "scores": scores,
                "novelty_constraints": [f"真实职业约束{i}", f"地方制度约束{i}"],
                "structural_fingerprint": f"身份{i}-欲望{i}-关系{i}-冲突{i}-手段{i}",
                "prior_work_comparison": f"已与本地旧作比较，候选{i}的机制和代价链不同",
                "costume_swap_test": f"候选{i}去除姓名时代地点后仍有独立因果骨架",
                "scene_causality": f"目标{i}→阻力{i}→选择{i}→代价{i}→状态变化{i}",
                "adversarial_review": f"独立审稿发现候选{i}的初版便利巧合并已改为人物选择",
            } for i in range(1, 13)]
            originality = {
                "banned_defaults": [f"默认套路{i}" for i in range(1, 11)],
                "entropy_pool": ["真实职业", "地方制度", "特殊物件"],
                "prior_work_scope": "已检查服务器本地全部既有小说项目的机制、关系和单元结构",
            }
            no_market = request(base, "/v1/ideations", token, "POST", {"genre": "女频快穿", "candidates": candidates})
            assert no_market[0] == 409
            market_job_id = "a" * 32
            stamp = "2026-06-30T00:00:00+00:00"
            with sqlite3.connect(state / "state.sqlite3") as con:
                con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)", (
                    market_job_id, "market_study", "completed", "{}",
                    json.dumps({"study_status": "ready", "usable_samples": 3, "samples": [{}, {}, {}]}),
                    None, stamp, stamp,
                ))
            too_few = request(base, "/v1/ideations", token, "POST", {
                "genre": "女频快穿", "market_job_id": market_job_id, "candidates": candidates[:11], **originality,
            })
            assert too_few[0] == 400 and too_few[2]["details"]["received_count"] == 11
            missing_gate = request(base, "/v1/ideations", token, "POST", {
                "genre": "女频快穿", "market_job_id": market_job_id, "candidates": candidates,
            })
            assert missing_gate[0] == 400 and "原创门禁失败" in missing_gate[2]["error"]
            idea = data(request(base, "/v1/ideations", token, "POST", {
                "genre": "女频快穿", "market_job_id": market_job_id, "candidates": candidates, **originality,
            }))
            selected = data(request(base, f"/v1/ideations/{idea['ideation_id']}/select", token, "POST", {"candidate_no": 1}))
            assert selected["stage"] == "selected"

            book = data(request(base, "/v1/books", token, "POST", {
                "ideation_id": idea["ideation_id"], "selected_working_title": "候选1",
                "title": "冒烟测试新书", "account": "account-b",
                "metadata": {"synopsis": "仅用于隔离测试"},
            }))
            assert book["stage"] == "trial_writing" and book["revision"] == 1
            book_id = book["id"]
            assert book["cover_status"] == "missing"
            fuzzy_query = urllib.parse.urlencode({"title": "冒烟新书", "account": "桃枝醒醒"})
            fuzzy = data(request(base, f"/v1/books?{fuzzy_query}", token))
            assert fuzzy["resolved"] is True and fuzzy["selected"]["book_id"] == book_id

            rebind_book = data(request(base, "/v1/books", token, "POST", {
                "ideation_id": idea["ideation_id"], "selected_working_title": "候选1",
                "title": "重绑测试书", "account": "account-b",
            }))
            replacement = json.loads(json.dumps(candidates, ensure_ascii=False))
            replacement[0]["working_title"] = "正确候选"
            replacement_id = "d" * 32
            with sqlite3.connect(state / "state.sqlite3") as con:
                con.execute("INSERT INTO ideations VALUES(?,?,'selected',?,1,?,?,?)", (
                    replacement_id, "女频快穿", json.dumps(replacement, ensure_ascii=False),
                    market_job_id, stamp, stamp,
                ))
            mismatch = request(base, "/v1/books", token, "POST", {
                "ideation_id": replacement_id, "selected_working_title": "正确候选",
                "title": "重绑测试书", "account": "account-b",
            })
            assert mismatch[0] == 409
            assert mismatch[2]["details"]["code"] == "ideation_mismatch"
            assert mismatch[2]["details"]["rebind_allowed"] is True
            rebound = data(request(base, f"/v1/books/{rebind_book['id']}/ideation-rebind", token, "POST", {
                "ideation_id": replacement_id, "selected_working_title": "正确候选",
                "title": "重绑测试书", "account": "account-b", "confirm_rebuild": True,
                "metadata": {"synopsis": "重绑后的简介"},
            }))
            assert rebound["rebound"] is True and rebound["id"] == rebind_book["id"]
            assert rebound["cover_status"] == "missing"
            rebound_cover = data(request(base, f"/v1/books/{rebind_book['id']}/cover-spec", token))
            assert rebound_cover["recovery_context"]["selected_candidate"]["working_title"] == "正确候选"
            bible = Path(rebound["path"]) / "设定/作品圣经.md"
            bible_text = bible.read_text(encoding="utf-8")
            bible_data = json.loads(bible_text[bible_text.index("{"):])
            assert bible_data["working_title"] == "正确候选"
            data(request(base, f"/v1/books/{rebind_book['id']}/chapters", token, "POST", {
                "expected_revision": 2,
                "chapters": [{"chapter_no": 1, "title": "已有正文", "body": "测" * 2600, "summary": "阻断重绑"}],
            }))
            blocked_rebind = request(base, f"/v1/books/{rebind_book['id']}/ideation-rebind", token, "POST", {
                "ideation_id": idea["ideation_id"], "selected_working_title": "候选1",
                "title": "重绑测试书", "account": "account-b", "confirm_rebuild": True,
            })
            assert blocked_rebind[0] == 409 and blocked_rebind[2]["details"]["rebind_allowed"] is False

            missing_cover = data(request(base, f"/v1/books/{book_id}/cover-spec", token))
            assert missing_cover["cover_status"] == "missing"
            assert missing_cover["recovery_context"]["title"] == "冒烟测试新书"
            cover_prompt = (
                "为当前女频快穿小说《冒烟测试新书》制作最终封面，作者：桃枝醒醒。"
                "画面表现现代女性在规则迷局中主动破局，人物、场景和光影均须匹配女频快穿题材。"
                "画面必须清晰完整显示书名和作者名，不得出现其他作品信息。最终尺寸严格为600×800 PNG。"
            )
            bad_cover = request(base, f"/v1/books/{book_id}/cover-spec", token, "PUT", {
                "cover_prompt": "生成一张普通封面",
            })
            assert bad_cover[0] == 400
            saved_cover = data(request(base, f"/v1/books/{book_id}/cover-spec", token, "PUT", {
                "cover_prompt": cover_prompt,
                "visual_brief": {"genre": "女频快穿", "forbidden": ["古装"]},
            }))
            assert saved_cover["cover_status"] == "prompt_saved"
            assert saved_cover["cover_prompt"] == cover_prompt
            assert saved_cover["manual_generation_required"] is True
            assert "禁止调用" in saved_cover["instruction"]
            resumed = data(request(base, "/v1/books", token, "POST", {
                "ideation_id": idea["ideation_id"], "selected_working_title": "候选1",
                "title": "冒烟测试新书", "account": "account-b",
            }))
            assert resumed["resumed"] is True and resumed["cover_status"] == "prompt_saved"

            chapters = []
            for no, char in enumerate("天地人", 1):
                chapters.append({
                    "chapter_no": no,
                    "title": f"试读单元{no}",
                    "body": char * (2000 if no == 1 else 2600),
                    "summary": f"第{no}章隔离测试摘要",
                })
            book = data(request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 1, "chapters": chapters,
            }))
            assert book["stage"] == "trial_writing" and book["revision"] == 2
            with sqlite3.connect(state / "state.sqlite3") as con:
                stored_title, stored_path = con.execute(
                    "SELECT title,file_path FROM chapter_drafts WHERE book_id=? AND chapter_no=1", (book_id,)
                ).fetchone()
            assert stored_title == "试读单元1"
            assert Path(stored_path).name == "第001章_试读单元1.md"

            preliminary_qa = data(request(base, f"/v1/books/{book_id}/qa", token, "POST", {"from": 1, "to": 3,
                "originality_review": {"scene_causality_checked": True, "cross_work_swap_checked": True,
                "ai_pattern_reviewed": True, "notes": "先验证不合格临时稿仍可覆盖修订，不进入正式正文。"}}))
            assert preliminary_qa["passed"] is False
            book = data(request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 2,
                "chapters": [{"chapter_no": 1, "title": "试读单元1", "body": "天" * 2600,
                              "summary": "第1章修订后摘要"}],
            }))
            assert book["stage"] == "trial_writing" and book["revision"] == 3
            blocked = request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 3,
                "chapters": [{"chapter_no": 4, "title": "试读单元4", "body": "玄" * 2600, "summary": "不得提前保存"}],
            })
            assert blocked[0] == 409

            qa_payload = {"from": 1, "to": 3, "originality_review": {
                "scene_causality_checked": True, "cross_work_swap_checked": True,
                "ai_pattern_reviewed": True, "notes": "逐章检查场景因果、旧作换皮风险和AI模板表达，未发现硬性问题。",
            }}
            missing_review = request(base, f"/v1/books/{book_id}/qa", token, "POST", {"from": 1, "to": 3})
            assert missing_review[0] == 400 and "原创门禁失败" in missing_review[2]["error"]
            qa = data(request(base, f"/v1/books/{book_id}/qa", token, "POST", qa_payload))
            assert qa["passed"] is True
            drafts = data(request(base, f"/v1/books/{book_id}/chapter-drafts?from=1&to=3", token))
            assert len(drafts["drafts"]) == 3 and all(x["qa_passed"] for x in drafts["drafts"])
            assert data(request(base, f"/v1/books/{book_id}/context", token))["book"]["stage"] == "trial_ready_for_review"
            approved = data(request(base, f"/v1/books/{book_id}/trial-approval", token, "POST", {}))
            assert approved["stage"] == "bulk_writing"
            with sqlite3.connect(state / "state.sqlite3") as con:
                assert con.execute("SELECT COUNT(*) FROM chapters WHERE book_id=?", (book_id,)).fetchone()[0] == 3
                assert con.execute("SELECT COUNT(*) FROM chapter_drafts WHERE book_id=?", (book_id,)).fetchone()[0] == 0
            batch = data(request(base, f"/v1/books/{book_id}/writing-batch", token, "PUT", {
                "approximate_words": 10000, "upload_mode": "review",
            }))
            assert batch["from_chapter"] == 4 and batch["target_chapters"] == 4
            assert batch["upload_mode"] == "review" and batch["status"] == "writing"

            resume = data(request(base, f"/v1/books/{book_id}/writing-resume", token))
            assert assert_actionable(resume)["type"] == "plan_segment"
            assert resume["next_action"]["action"] == "contract_create"
            writing_contract_payload = dict(resume["next_action"]["payload_schema"])
            assert (writing_contract_payload["from"], writing_contract_payload["to"]) == (4, 7)
            assert "segment_from" not in writing_contract_payload and "segment_to" not in writing_contract_payload
            writing_contract_payload["contract"] = contract_payload(4, 7)["contract"]
            contract = workflow(base, token, "contract_create", book_id, writing_contract_payload)
            contract_id = contract["id"]
            bypass = request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 4,
                "chapters": [{"chapter_no": 4, "title": "新世界开端", "body": "玄" * 2600, "summary": "第4章"}],
            })
            assert bypass[0] == 409 and "禁止绕过" in bypass[2]["error"]
            body4 = "林小满主动选择承担代价，亲情因此发生变化。" * 180
            unreviewed = request(base, f"/v1/books/{book_id}/chapter-checkpoints", token, "POST", {
                "expected_revision": 4, "idempotency_key": f"{book_id}-chapter-004-unreviewed",
                "contract_id": contract_id,
                "chapter": {"chapter_no": 4, "title": "新世界开端", "body": body4, "summary": "第4章"},
                "state": checkpoint_state(4, 4), "self_review": self_review(body4),
            })
            assert unreviewed[0] == 409 and "候选稿独立审稿" in unreviewed[2]["error"]
            body4 = review_candidate(base, token, book_id, 4, contract_id,
                                     "新世界开端", body4, "第4章")
            checkpoint4 = data(request(base, f"/v1/books/{book_id}/chapter-checkpoints", token, "POST", {
                "expected_revision": 4, "idempotency_key": f"{book_id}-chapter-004-v1",
                "contract_id": contract_id,
                "chapter": {"chapter_no": 4, "title": "新世界开端", "body": body4, "summary": "第4章"},
                "state": checkpoint_state(4, 4), "self_review": self_review(body4),
            }))
            assert checkpoint4["committed_revision"] == 5
            stale = request(base, f"/v1/books/{book_id}/state", token, "PUT", {"expected_revision": 4, "state": {}})
            assert stale[0] == 409
            chapter4_qa = data(request(base, f"/v1/books/{book_id}/qa", token, "POST", {
                "from": 4, "to": 4, "originality_review": {
                    "scene_causality_checked": True, "cross_work_swap_checked": True,
                    "ai_pattern_reviewed": True, "notes": "逐章检查场景因果、旧作换皮风险和AI模板表达，确认可以继续。",
                },
            }))
            assert chapter4_qa["passed"] is True
            body5 = "林小满亲手改变关系，她接受损失并推动家人作出回应。" * 170
            body5 = review_candidate(base, token, book_id, 5, contract_id,
                                     "原子检查点", body5, "第5章检查点摘要")
            checkpoint_payload = {
                "expected_revision": 5,
                "idempotency_key": f"{book_id}-chapter-005-v1",
                "contract_id": contract_id,
                "chapter": {"chapter_no": 5, "title": "原子检查点", "body": body5,
                            "summary": "第5章检查点摘要"},
                "state": checkpoint_state(5, 5), "self_review": self_review(body5),
            }
            checkpoint = data(request(base, f"/v1/books/{book_id}/chapter-checkpoints", token, "POST",
                                      checkpoint_payload))
            assert checkpoint["checkpoint_committed"] is True
            assert checkpoint["committed_revision"] == 6
            assert assert_actionable(checkpoint["resume"])["type"] == "run_qa"
            assert checkpoint["resume"]["next_action"]["chapter_no"] == 5
            assert checkpoint["resume"]["next_action"]["action"] == "quality_check"
            replay = data(request(base, f"/v1/books/{book_id}/chapter-checkpoints", token, "POST",
                                  checkpoint_payload))
            assert replay["idempotent_replay"] is True and replay["committed_revision"] == 6
            conflicting_replay = dict(checkpoint_payload)
            conflicting_replay["chapter"] = dict(checkpoint_payload["chapter"], body="异" * 2600)
            assert request(base, f"/v1/books/{book_id}/chapter-checkpoints", token, "POST",
                           conflicting_replay)[0] == 409
            resume = data(request(base, f"/v1/books/{book_id}/writing-resume", token))
            assert resume["book"]["revision"] == 6 and resume["next_action"]["chapter_no"] == 5
            checkpoint_context = data(request(base, f"/v1/books/{book_id}/context", token))
            assert "完整上下文追踪" in checkpoint_context["state"]["context"]
            assert checkpoint_context["state"]["structured"]["last_chapter"] == 5
            staged_path = txt / "冒烟测试新书" / "草稿暂存" / "待确认状态.json"
            oversized_state = json.loads(staged_path.read_text(encoding="utf-8"))
            oversized_state["chapter_index"] += "\n" + ("历史索引内容" * 12000)
            staged_path.write_text(json.dumps(oversized_state, ensure_ascii=False), encoding="utf-8")
            compact_context = workflow(base, token, "context_get", book_id, {})
            assert compact_context["state_manifest"]["chapter_index"]["preview_truncated"] is True
            context_page = workflow(base, token, "context_get", book_id, {
                "section": "chapter_index", "offset": 0, "limit": 800,
            })
            assert len(context_page["content"]) <= 800 and context_page["has_more"] is True
            old_jobs = ["b" * 32, "c" * 32]
            with sqlite3.connect(state / "state.sqlite3") as con:
                for old_id, status in zip(old_jobs, ("queued", "running")):
                    con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)", (
                        old_id, "upload_drafts", status,
                        json.dumps({"book_id": book_id, "from": 4, "to": 4}),
                        None, None, stamp, stamp,
                    ))
            newest = data(request(base, f"/v1/books/{book_id}/draft-upload-jobs", token, "POST", {
                "from": 4, "to": 4,
            }))
            assert sorted(newest["superseded_job_ids"]) == sorted(old_jobs)
            with sqlite3.connect(state / "state.sqlite3") as con:
                statuses = dict(con.execute("SELECT id,status FROM jobs WHERE id IN (?,?)", old_jobs).fetchall())
            assert statuses == {old_jobs[0]: "superseded", old_jobs[1]: "superseded"}
            with sqlite3.connect(state / "state.sqlite3") as con:
                con.execute("UPDATE chapters SET uploaded=1 WHERE book_id=? AND chapter_no=1", (book_id,))
                con.execute("INSERT INTO audit(at,action,book_id,details_json) VALUES(?,?,?,?)", (
                    stamp, "drafts_verified_manual_recovery", book_id,
                    json.dumps({"rows": [{"no": 1, "title": "第001章 试读单元1", "words": 2600}]}, ensure_ascii=False),
                ))
            draft_status = data(request(base, f"/v1/books/{book_id}/draft-status", token))
            assert draft_status["uploaded_chapters"] == [1]
            assert draft_status["latest_platform_verification"]["rows"][0]["words"] == 2600
            assert draft_status["latest_upload_job"]["status"] in {"queued", "running", "failed"}
            with sqlite3.connect(state / "state.sqlite3") as con:
                draft_paths = [row[0] for row in con.execute(
                    "SELECT file_path FROM chapter_drafts WHERE book_id=?", (book_id,)
                )]
                con.execute("DELETE FROM chapter_drafts WHERE book_id=?", (book_id,))
                con.execute("UPDATE writing_batches SET status='completed' WHERE book_id=?", (book_id,))
            for draft_path in draft_paths:
                Path(draft_path).unlink(missing_ok=True)
            revision = workflow(base, token, "revision_configure", book_id, {
                "chapter_numbers": [1, 2, 3], "mode": "review",
            })
            assert assert_actionable(revision)["type"] == "plan_revision_segment"
            revision_id = revision["revision_batch"]["id"]
            redirected = data(request(base, f"/v1/books/{book_id}/writing-resume", token))
            assert redirected["revision_batch"]["id"] == revision_id
            assert assert_actionable(redirected)["type"] == "plan_revision_segment"
            revision_contract_payload = dict(revision["next_action"]["payload_schema"])
            assert (revision_contract_payload["from"], revision_contract_payload["to"]) == (1, 3)
            assert "segment_from" not in revision_contract_payload and "segment_to" not in revision_contract_payload
            revision_contract_payload["to"] = 2
            revision_contract_payload["contract"] = contract_payload(1, 2)["contract"]
            revision_contract = workflow(base, token, "contract_create", book_id, revision_contract_payload)
            revised_body = "林小满主动纠正旧日错误，她付出代价并重新赢得亲人的信任。" * 160
            revised_body = review_candidate(
                base, token, book_id, 1, revision_contract["id"], "修订后标题", revised_body,
                "第1章修订摘要", revision_id,
            )
            revised_body2 = "林小满主动面对第二个旧日矛盾，她拒绝方便的捷径并承担误解，最终让家人作出自己的选择。" * 150
            precreated_chapter2 = workflow(base, token, "candidate_save", book_id, {
                "contract_id": revision_contract["id"], "revision_batch_id": revision_id,
                "chapter": {"chapter_no": 2, "title": "第二章修订标题", "body": revised_body2,
                            "summary": "第2章修订摘要"},
            })
            assert precreated_chapter2["next_action"]["chapter_no"] == 1
            assert precreated_chapter2["next_action"]["action"] == "checkpoint_commit"
            revised = workflow(base, token, "checkpoint_commit", book_id, {
                "expected_revision": revision["book"]["revision"],
                "idempotency_key": f"{book_id}-revision-001-v1", "revision_batch_id": revision_id,
                "contract_id": revision_contract["id"], "self_review": self_review(revised_body),
                "chapter": {"chapter_no": 1, "title": "修订后标题", "body": revised_body,
                            "summary": "第1章修订摘要"},
                "state_patch": checkpoint_patch(1),
            })
            assert revised["checkpoint_committed"] is True
            assert assert_actionable(revised)["type"] == "run_qa"
            assert revised["next_action"]["action"] == "quality_check"
            revision_qa = workflow(base, token, "quality_check", book_id, {
                "from": 1, "to": 1, "originality_review": {
                    "scene_causality_checked": True, "cross_work_swap_checked": True,
                    "ai_pattern_reviewed": True, "notes": "修订章已检查场景因果、跨书换皮和AI模板表达。",
                },
            })
            assert revision_qa["passed"] is True
            assert assert_actionable(revision_qa)["type"] == "critique_chapter"
            assert revision_qa["next_action"]["chapter_no"] == 2
            resumed_after_qa = data(request(base, "/v1/actions/novel", token, "POST", {
                "action": "revision_get", "book_id": book_id,
                "payload_json": json.dumps({"revision_batch_id": revision_id}),
            }))
            assert assert_actionable(resumed_after_qa)["type"] == "critique_chapter"
            assert resumed_after_qa["next_action"]["chapter_no"] == 2
            revised_body2 = review_candidate(
                base, token, book_id, 2, revision_contract["id"], "第二章修订标题", revised_body2,
                "第2章修订摘要", revision_id,
            )
            revised2 = workflow(base, token, "checkpoint_commit", book_id, {
                "expected_revision": revised["committed_revision"],
                "idempotency_key": f"{book_id}-revision-002-v1", "revision_batch_id": revision_id,
                "contract_id": revision_contract["id"], "self_review": self_review(revised_body2),
                "chapter": {"chapter_no": 2, "title": "第二章修订标题", "body": revised_body2,
                            "summary": "第2章修订摘要"},
                "state_patch": checkpoint_patch(2),
            })
            assert revised2["checkpoint_committed"] is True
            assert assert_actionable(revised2)["type"] == "run_qa"
            revision_qa2 = workflow(base, token, "quality_check", book_id, {
                "from": 2, "to": 2, "originality_review": {
                    "scene_causality_checked": True, "cross_work_swap_checked": True,
                    "ai_pattern_reviewed": True, "notes": "第二个修订章已检查场景因果、跨书换皮和AI模板表达。",
                },
            })
            assert revision_qa2["passed"] is True
            assert assert_actionable(revision_qa2)["type"] == "review_segment"
            segment_review = workflow(base, token, "contract_review", book_id, {
                    "contract_id": revision_contract["id"], "review": {
                        "protagonist_agency_passed": True, "genre_promise_passed": True,
                        "emotional_arc_passed": True, "structure_diversity_passed": True,
                        "title_variety_passed": True, "exposition_density_passed": True,
                        "tracking_integrity_passed": True,
                        "chapter_findings": [
                            {"chapter_no": 1, "finding": "主角主动纠正旧日错误并承担关系受损的代价，最终通过行动重新赢得信任，情绪变化和状态变化均落到正文。"},
                            {"chapter_no": 2, "finding": "主角面对第二个矛盾时拒绝方便捷径并承担误解，其他人物保留独立选择，结果由双方行动共同形成。"},
                        ],
                        "cross_chapter_notes": "本次单章修订恢复了主角能动性，冲突由人物选择推动，情绪变化落在具体关系上，并删除了报告体解释和重复规则描述。" * 2,
                    }
                })
            assert segment_review["passed"] is True
            assert assert_actionable(segment_review)["type"] == "plan_revision_segment"
            next_segment = data(request(base, "/v1/actions/novel", token, "POST", {
                "action": "revision_get", "book_id": book_id,
                "payload_json": json.dumps({"revision_batch_id": revision_id}),
            }))
            assert assert_actionable(next_segment)["type"] == "plan_revision_segment"
            assert (next_segment["next_action"]["from"], next_segment["next_action"]["to"]) == (3, 3)
            revision_contract_payload2 = dict(next_segment["next_action"]["payload_schema"])
            assert (revision_contract_payload2["from"], revision_contract_payload2["to"]) == (3, 3)
            revision_contract_payload2["contract"] = contract_payload(3, 3)["contract"]
            revision_contract2 = workflow(base, token, "contract_create", book_id, revision_contract_payload2)
            revised_body3 = "林小满在第三次冲突里主动公开自己的错误，她承担同伴离开的结果，并用行动兑现此前承诺。" * 155
            revised_body3 = review_candidate(
                base, token, book_id, 3, revision_contract2["id"], "第三章修订标题", revised_body3,
                "第3章修订摘要", revision_id,
            )
            revised3 = workflow(base, token, "checkpoint_commit", book_id, {
                "expected_revision": revised2["committed_revision"],
                "idempotency_key": f"{book_id}-revision-003-v1", "revision_batch_id": revision_id,
                "contract_id": revision_contract2["id"], "self_review": self_review(revised_body3),
                "chapter": {"chapter_no": 3, "title": "第三章修订标题", "body": revised_body3,
                            "summary": "第3章修订摘要"},
                "state_patch": checkpoint_patch(3),
            })
            assert revised3["checkpoint_committed"] is True
            assert assert_actionable(revised3)["type"] == "run_qa"
            revision_qa3 = workflow(base, token, "quality_check", book_id, {
                "from": 3, "to": 3, "originality_review": {
                    "scene_causality_checked": True, "cross_work_swap_checked": True,
                    "ai_pattern_reviewed": True, "notes": "第三个修订章已检查场景因果、跨书换皮和AI模板表达。",
                },
            })
            assert revision_qa3["passed"] is True
            assert assert_actionable(revision_qa3)["type"] == "review_segment"
            segment_review2 = workflow(base, token, "contract_review", book_id, {
                    "contract_id": revision_contract2["id"], "review": {
                        "protagonist_agency_passed": True, "genre_promise_passed": True,
                        "emotional_arc_passed": True, "structure_diversity_passed": True,
                        "title_variety_passed": True, "exposition_density_passed": True,
                        "tracking_integrity_passed": True,
                        "chapter_findings": [{"chapter_no": 3, "finding": "主角公开自己的错误并承担同伴离开的真实结果，随后通过行动兑现承诺，状态变化不依赖旁人替她解决。"}],
                        "cross_chapter_notes": "第二个合同采用公开错误与承诺兑现推动剧情，和前一合同的关系修复及拒绝捷径不同；人物选择、实际代价和情绪结果均由场景动作完成。" * 2,
                    }
                })
            assert segment_review2["passed"] is True
            assert assert_actionable(segment_review2)["type"] == "await_user_review"
            awaiting_review = data(request(base, "/v1/actions/novel", token, "POST", {
                "action": "revision_get", "book_id": book_id,
                "payload_json": json.dumps({"revision_batch_id": revision_id}),
            }))
            assert assert_actionable(awaiting_review)["type"] == "await_user_review"
            approved_revision = data(request(base, "/v1/actions/novel", token, "POST", {
                "action": "revision_approve", "book_id": book_id,
                "payload_json": json.dumps({"revision_batch_id": revision_id}),
            }))
            assert approved_revision["revision_batch"]["status"] == "completed"
            with sqlite3.connect(state / "state.sqlite3") as con:
                revised_row = con.execute(
                    "SELECT title,uploaded FROM chapters WHERE book_id=? AND chapter_no=1", (book_id,)
                ).fetchone()
                revised_row2 = con.execute(
                    "SELECT title,uploaded FROM chapters WHERE book_id=? AND chapter_no=2", (book_id,)
                ).fetchone()
                revised_row3 = con.execute(
                    "SELECT title,uploaded FROM chapters WHERE book_id=? AND chapter_no=3", (book_id,)
                ).fetchone()
                revision_status = con.execute("SELECT status FROM revision_batches WHERE id=?", (revision_id,)).fetchone()[0]
            assert revised_row == ("修订后标题", 0)
            assert revised_row2 == ("第二章修订标题", 0)
            assert revised_row3 == ("第三章修订标题", 0) and revision_status == "completed"
            assert request(base, f"/v1/books/{book_id}/publish", token, "POST", {})[0] == 404
            print("smoke: PASS")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
