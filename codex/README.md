# Codex Skills Sync

This folder stores Codex skills that can be synced through Git.

## Use On A New Computer

After cloning this repository, run PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File D:\ai\codex\link-codex-skills.ps1
```

The script backs up the existing `%USERPROFILE%\.codex\skills` folder and creates a junction so Codex reads skills from:

```text
D:\ai\codex\skills
```

Restart Codex after running the script.

## Current Custom Skill

The Android app/APK workflow skill is:

```text
D:\ai\codex\skills\android-apk-builder
```

Its key rule: browser previews must match the installed Android APK UI, using shared design tokens and parity checks.
