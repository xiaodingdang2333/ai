# Codex Skills Sync And Android APK Workflow

This note records the workflow built on 2026-05-25 so another computer can continue without relying on chat history.

## What Was Set Up

Codex skills are synced through the Git repository at:

```text
D:\ai
```

The synced skills root is:

```text
D:\ai\codex\skills
```

On this computer, the normal Codex skills folder:

```text
%USERPROFILE%\.codex\skills
```

is a Windows junction pointing to:

```text
D:\ai\codex\skills
```

This means future created or installed skills go into the Git-synced folder.

## Use On Another Computer

1. Clone or pull the `ai` repository:

```powershell
git clone git@github.com:xiaodingdang2333/ai.git D:\ai
```

If `D:\ai` already exists:

```powershell
cd D:\ai
git pull
```

2. Link Codex skills to the synced folder:

```powershell
powershell -ExecutionPolicy Bypass -File D:\ai\codex\link-codex-skills.ps1
```

3. Restart Codex.

The script backs up any existing `%USERPROFILE%\.codex\skills` folder, then creates a junction to `D:\ai\codex\skills`.

## Important Skill

The custom Android app skill is:

```text
D:\ai\codex\skills\android-apk-builder
```

Trigger it when asking Codex to:

- create an Android app
- generate an APK
- build a single-device/offline app
- use GitHub Actions to package an APK
- make a browser preview before packaging
- keep browser preview and installed APK visually identical

Core rule:

> The browser preview is a contract for the APK UI. Do not make a polished `preview.html` unless the Android UI is implemented from the same design tokens and layout rules.

Detailed parity rules are in:

```text
D:\ai\codex\skills\android-apk-builder\references\preview-parity.md
```

## Android APK Workflow Used

For the photo-to-PDF app, the workflow was:

1. Create a native Android Java project locally.
2. Add `preview.html` for browser/Codex UI review.
3. Configure GitHub Actions to build the debug APK in the cloud.
4. Push project to GitHub.
5. Read Actions status and build logs.
6. Fix build errors.
7. Download `app-debug.apk` artifact locally.
8. Compare real phone screenshots against `preview.html`.
9. Adjust Android UI to match the web preview.
10. Rebuild APK.

The Android project repository used in this session:

```text
git@github.com:xiaodingdang2333/PhotoPdfOrganizer.git
```

Local project path on this computer:

```text
C:\Users\小叮当\PhotoPdfOrganizer
```

Latest rebuilt APK path from this session:

```text
C:\Users\小叮当\PhotoPdfOrganizer-apk-preview-ui\app-debug.apk
```

## GitHub Actions Pattern

Use cloud builds when the local computer does not have Android SDK, Gradle, or JDK 17 installed.

The workflow should:

- use `actions/setup-java@v4` with Temurin JDK 17
- use `android-actions/setup-android@v3`
- install Android platform/build tools with `sdkmanager`
- use Gradle 8.7
- build with `gradle assembleDebug --stacktrace --info`
- upload both APK and `build.log`

Always upload `build.log`, including on failure, because GitHub annotations often hide the real Gradle error.

## Sync New Skill Changes

After creating, editing, or installing skills:

```powershell
cd D:\ai
git status
git add codex
git commit -m "Update Codex skills"
git push
```

The repository `.gitignore` excludes Python cache files:

```text
__pycache__/
*.pyc
```

## Notes About Chat History

Chat history may or may not appear on another computer, depending on Codex account/cloud sync behavior. Do not rely on chat history for continuity.

Use this note, the synced skill files, and the Git repositories as the durable record.
