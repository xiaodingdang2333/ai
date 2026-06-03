---
name: voice-design
description: Generate realistic fictional voices across age groups and genders using the official OmniVoice Hugging Face Space. Use when the user asks for natural child, teenager, adult, middle-aged, or elderly voices; male or female voices; voice design; realistic spoken audio; classroom questions; narration; or age/gender voice variants. Use voice cloning only for authorized reference audio.
---

# Voice Design

Use the official OmniVoice Hugging Face Space through the lightweight client. Do not install the local OmniVoice model on this machine: it has an AMD Radeon RX 6750 GRE on Windows, while the supported local GPU paths are not suitable here.

## Runtime

- Python: `C:\Users\Administrator\.local\bin\python.exe`
- Virtual environment: `F:\ai\anything\voice-design-runtime\.venv`
- Script: `C:\Users\Administrator\.codex\skills\voice-design\scripts\generate_voice.py`

## Generate

```powershell
& 'F:\ai\anything\voice-design-runtime\.venv\Scripts\python.exe' `
  'C:\Users\Administrator\.codex\skills\voice-design\scripts\generate_voice.py' `
  --text '老师，我有一个问题。' `
  --output 'F:\ai\anything\voice.wav' `
  --gender male `
  --age child `
  --pitch high
```

Supported controls:

- `--gender`: `auto`, `male`, `female`
- `--age`: `auto`, `child`, `teenager`, `young-adult`, `middle-aged`, `elderly`
- `--pitch`: `auto`, `very-low`, `low`, `moderate`, `high`, `very-high`
- `--style`: `auto`, `whisper`
- `--speed`: float, default `1.0`

## Safety

- Generate fictional voices freely.
- Clone a real person's voice only when the user confirms authorization.
- Do not present generated audio as authentic evidence or as a real person's recording.
