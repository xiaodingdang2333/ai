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
            privacy = request(base, "/privacy")
            assert privacy[0] == 200 and privacy[1].startswith("text/html")

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

            chapter4 = data(request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 4,
                "chapters": [{"chapter_no": 4, "title": "新世界开端", "body": "玄" * 2600, "summary": "第4章"}],
            }))
            assert chapter4["revision"] == 5
            stale = request(base, f"/v1/books/{book_id}/state", token, "PUT", {"expected_revision": 4, "state": {}})
            assert stale[0] == 409
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
