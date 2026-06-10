import argparse
import shutil
from pathlib import Path

from gradio_client import Client


CHOICES = {
    "gender": {
        "auto": "Auto",
        "male": "Male / \u7537",
        "female": "Female / \u5973",
    },
    "age": {
        "auto": "Auto",
        "child": "Child / \u513f\u7ae5",
        "teenager": "Teenager / \u5c11\u5e74",
        "young-adult": "Young Adult / \u9752\u5e74",
        "middle-aged": "Middle-aged / \u4e2d\u5e74",
        "elderly": "Elderly / \u8001\u5e74",
    },
    "pitch": {
        "auto": "Auto",
        "very-low": "Very Low Pitch / \u6781\u4f4e\u97f3\u8c03",
        "low": "Low Pitch / \u4f4e\u97f3\u8c03",
        "moderate": "Moderate Pitch / \u4e2d\u97f3\u8c03",
        "high": "High Pitch / \u9ad8\u97f3\u8c03",
        "very-high": "Very High Pitch / \u6781\u9ad8\u97f3\u8c03",
    },
    "style": {
        "auto": "Auto",
        "whisper": "Whisper / \u8033\u8bed",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a fictional designed voice using the official OmniVoice Space.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--gender", choices=CHOICES["gender"], default="auto")
    parser.add_argument("--age", choices=CHOICES["age"], default="auto")
    parser.add_argument("--pitch", choices=CHOICES["pitch"], default="auto")
    parser.add_argument("--style", choices=CHOICES["style"], default="auto")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--cfg", type=float, default=2.0)
    return parser.parse_args()


def main():
    args = parse_args()
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    downloads = out_path.parent / ".omnivoice-downloads"
    downloads.mkdir(exist_ok=True)

    client = Client(
        "https://k2-fsa-omnivoice.hf.space",
        httpx_kwargs={"timeout": 90, "trust_env": False},
        download_files=downloads,
        verbose=False,
    )
    audio, status = client.predict(
        args.text,
        args.language,
        args.steps,
        args.cfg,
        True,
        args.speed,
        None,
        True,
        True,
        CHOICES["gender"][args.gender],
        CHOICES["age"][args.age],
        CHOICES["pitch"][args.pitch],
        CHOICES["style"][args.style],
        "Auto",
        "Auto",
        api_name="/_design_fn",
    )
    if not audio:
        raise RuntimeError(f"OmniVoice returned no audio. Status: {status}")
    shutil.copyfile(audio, out_path)
    print(out_path)


if __name__ == "__main__":
    main()
