---
name: video-chord-sheet
description: Create low-token, accurate guitar chord sheets from short videos or screenshots where chord diagrams are already visible. Use when the user asks to identify visible chords, transcribe a song into a lyric-and-chord sheet, preserve the video's exact chord fingerings, add an intro chord sequence before lyrics, or export the result as HTML/PNG/PDF.
---

# Video Chord Sheet

Goal: finish accurately with minimal context. Prefer reading visible chord labels/diagrams from frames over audio analysis.

## Fast Workflow

1. Inspect video duration and extract a contact sheet at low fps.
   - Use `ffmpeg` if installed.
   - If not, create a temp npm folder and install/use `ffmpeg-static`.
   - Start with `fps=0.5,scale=360:-1,tile=4x5`; raise fps only when chord changes are missed.
2. Read chord labels from the contact sheet.
   - Do not infer from audio unless the video lacks chord labels.
   - If the user says “the first N chords are intro,” keep those chords in a separate intro block and start lyrics at chord `N+1`.
3. Preserve exact fingerings by cropping the chord diagrams from video frames.
   - Extract a few clear full-size frames around each chord group.
   - Crop each unique chord diagram into an asset image.
   - Use cropped assets in the top chord diagram section instead of redrawing from memory.
4. Handle lyrics safely.
   - If lyrics are copyrighted and not user-provided, do not reproduce the full lyrics; ask the user to provide text or use short placeholders.
   - If the user provides lyrics in chat, format that text into the sheet.
5. Generate output with `scripts/render-sheet.mjs`.
   - Write a small JSON spec with title, metadata, chord image assets, intro rows, and lyric lines.
   - Run the script to produce HTML.
   - Export PNG with headless Chrome/Edge.

## Useful Commands

Install ffmpeg-static in a temp task folder:

```powershell
npm init -y
npm install ffmpeg-static
$ffmpeg = node -e "console.log(require('ffmpeg-static'))"
```

Contact sheet:

```powershell
& $ffmpeg -hide_banner -i "input.mp4" -vf "fps=0.5,scale=360:-1,tile=4x5" -q:v 3 "contact_%02d.jpg" -y
```

Single frame:

```powershell
& $ffmpeg -hide_banner -ss 00:00:24 -i "input.mp4" -frames:v 1 -q:v 2 "frame_24.jpg" -y
```

Crop a chord diagram:

```powershell
& $ffmpeg -hide_banner -i "frame_24.jpg" -vf "crop=110:135:105:165" -frames:v 1 -q:v 2 "Fsm7.jpg" -y
```

Render HTML:

```powershell
node "C:\Users\Administrator\.codex\skills\video-chord-sheet\scripts\render-sheet.mjs" spec.json output.html
```

Export PNG:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 --window-size=1000,3600 --screenshot="sheet.png" "file:///C:/path/output.html"
```

## JSON Spec Shape

Use this compact schema:

```json
{
  "title": "Song",
  "meta": "Artist / video chord sheet / key",
  "diagrams": [{"name": "E", "src": "chord-assets/E.jpg"}],
  "intro": {
    "label": "Intro: first 16 chords, no lyrics",
    "rows": [
      {"label": "1-4", "chords": ["E", "E/G#", "Asus2", "Am6"]}
    ]
  },
  "sections": [
    {
      "title": "Lyrics: start at chord 17",
      "lines": [
        [{"chord": "E", "text": "lyric phrase"}, {"chord": "B/D#", "text": "lyric phrase"}]
      ]
    }
  ]
}
```

Keep each lyric phrase short enough that the chord sits visually over the intended words. Split a final syllable into its own phrase when a passing chord lands on it.
