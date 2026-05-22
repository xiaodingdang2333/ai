import base64
import json
import os
import sys
import urllib.error
import urllib.request

key = os.environ.get("GPT_IMAGE_API_KEY")
if not key:
    print("请先设置环境变量 GPT_IMAGE_API_KEY")
    sys.exit(1)

prompt = "Fanqie Chinese web novel cover, vibrant high contrast xianxia revenge fantasy. Title text '渡厄簿：她不替天命受罚了' at top center, large bold golden Chinese brush calligraphy, clear and readable. Author name '桃枝醒醒' at bottom center, small elegant white-gold Chinese text with thin gold divider. A cold powerful young Chinese heroine with long black hair, black and white xianxia robes with dark red accents, holding an open black fate ledger, standing on a thunder platform. Purple-gold lightning, broken chains, shattered white bone crown, storm clouds, faint kneeling sect disciples in background. Character dominates the cover, sharp face, calm strong eyes. Professional digital painting, portrait 2:3, 1024x1536, no watermark, no extra text."

endpoints = [
    "https://code.newcli.com/codex/v1/images/generations",
    "https://code.newcli.com/v1/images/generations",
    "https://code.newcli.com/codex/images/generations",
]
models = ["gpt-image-2"]
headers = {
    "Authorization": "Bearer " + key,
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
}

errors = []
for endpoint in endpoints:
    for model in models:
        payload = {
            "model": model,
            "prompt": prompt,
            "size": "1024x1536",
            "n": 1,
            "response_format": "b64_json",
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            errors.append(f"{endpoint} model={model} -> HTTP {e.code}: {body[:300]}")
            continue
        except Exception as e:
            errors.append(f"{endpoint} model={model} -> {type(e).__name__}: {e}")
            continue

        item = result.get("data", [{}])[0]
        if item.get("b64_json"):
            out_path = "渡厄簿：她不替天命受罚了/封面/封面_v1_桃枝醒醒.png"
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(item["b64_json"]))
            print(f"saved {out_path} via endpoint={endpoint} model={model}")
            sys.exit(0)
        if item.get("url"):
            print("image url:", item["url"])
            sys.exit(0)
        errors.append(f"{endpoint} model={model} -> unexpected: {json.dumps(result, ensure_ascii=False)[:300]}")

print("全部尝试失败：")
for error in errors:
    print(error)
sys.exit(1)
