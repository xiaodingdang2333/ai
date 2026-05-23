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

prompt = """A modern urban suspense romance novel cover. The main subject is a young woman (around 27 years old) standing in profile on a rainy night street in an old urban district. She wears a simple dark trench coat or jacket, holding a yellowed old letter in one hand, slightly looking down at it, with raindrops falling from her hair.

The background shows a blurred rainy night cityscape: aged brick walls, wet cobblestone paths, hazy streetlamp halos diffusing in the rain, and distant outlines of old houses about to be demolished. Color palette: deep blue, gray, and dark gold tones, creating a damp, nostalgic, and mysterious atmosphere.

Fine rain threads throughout the image. The woman's silhouette is clear but not overly bright in the rainy night. Overall style is realistic with cinematic quality and literary aesthetics. Character temperament: independent, calm, with a hint of weariness and determination.

Title "雨夜来信" in elegant Chinese Song or Kai typeface, warm gold or off-white color, positioned at the top or side of the composition, clearly legible. Author name "[作者笔名]" in smaller font below the title or at the bottom.

Overall mood: delicate, suspenseful, nostalgic, urban texture, modern romance. Professional digital painting, portrait 2:3, 1024x1536, no watermark."""

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
            out_path = "旧雨来信/封面/雨夜来信_封面_v1.png"
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
