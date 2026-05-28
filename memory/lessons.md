# Lessons

- 2026-05-26: For chord videos where chords are visible, read frame text/diagrams instead of analyzing audio. Use low-fps contact sheets to save tokens and time.
- 2026-05-26: When the user asks for exact chord fingerings from a video, crop the visible chord diagrams from video frames instead of redrawing from memory.
- 2026-05-26: For lyric chord sheets, separate intro chords when the user says the first N chords are intro; lyrics start at chord N+1.
- 2026-05-26: For image format conversion, use local PowerShell/System.Drawing when possible and return the output path.
- 2026-05-27: If a requested video-generation connector fails authentication, fall back to local FFmpeg plus local TTS when that satisfies the task.
