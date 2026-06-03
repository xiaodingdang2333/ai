# Lessons

- 2026-05-26: For chord videos where chords are visible, read frame text/diagrams instead of analyzing audio. Use low-fps contact sheets to save tokens and time.
- 2026-05-26: When the user asks for exact chord fingerings from a video, crop the visible chord diagrams from video frames instead of redrawing from memory.
- 2026-05-26: For lyric chord sheets, separate intro chords when the user says the first N chords are intro; lyrics start at chord N+1.
- 2026-05-26: For image format conversion, use local PowerShell/System.Drawing when possible and return the output path.
- 2026-05-27: If a requested video-generation connector fails authentication, fall back to local FFmpeg plus local TTS when that satisfies the task.
- 2026-06-01: Fanqie draft uploads may show a browser-level “离开此网站” confirmation or an in-page “有刚刚更新的草稿，是否继续编辑？” prompt. Upload automation should automatically choose “离开” and “继续编辑”, and should verify the final draft list once instead of repeatedly switching pages.
- 2026-06-01: On this Windows machine, Python is managed by `uv`. Ensure `C:\Users\Administrator\.local\bin\python.exe` is used before `WindowsApps\python.exe`. Do not reinstall Python merely because the Microsoft Store placeholder appears in `Get-Command`.
- 2026-06-01: This machine has an AMD Radeon RX 6750 GRE. For realistic age/gender voice design, use the official OmniVoice Hugging Face Space through the lightweight `voice-design` skill instead of attempting a local OmniVoice model install.
