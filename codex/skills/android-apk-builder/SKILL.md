---
name: android-apk-builder
description: Build single-device Android apps and APKs, especially when the user wants Codex to create an Android app, produce an installable APK, use GitHub Actions or cloud CI for packaging, or first review a browser preview before packaging. Use for native Android Java/Kotlin projects, lightweight offline apps, camera/gallery/file/PDF utilities, and workflows where the browser preview must visually match the installed APK.
---

# Android APK Builder

## Core Rule

Treat the browser preview as a contract for the APK UI. Do not create a polished `preview.html` that the Android app only approximates. Use one shared design specification and implement both the web preview and Android UI from it.

For strict parity requirements, read [preview-parity.md](references/preview-parity.md).

## Workflow

1. Clarify the app's core workflow, permissions, storage needs, and target Android range.
2. Check local tooling: `java`, `javac`, `gradle`, Android SDK, existing project files, and Git remote.
3. If local Android tooling is missing or slow to install, prefer GitHub Actions cloud packaging.
4. Create a minimal native Android project unless the user asks for Flutter/React Native.
5. Create `preview.html` before APK packaging when the user wants to review UI first.
6. Keep `preview.html` and Android UI synchronized from the same design spec.
7. Push to GitHub, let Actions build the debug APK, inspect failures, fix, and re-run.
8. Download the APK artifact locally and give the user the exact path.

## Project Defaults

Prefer this structure for small native Android apps:

```text
ProjectName/
  settings.gradle
  build.gradle
  gradle.properties
  preview.html
  .github/workflows/android-apk.yml
  app/
    build.gradle
    src/main/AndroidManifest.xml
    src/main/java/<package>/MainActivity.java
    src/main/res/values/styles.xml
    src/main/res/xml/file_paths.xml
```

Use Java for the first version when speed and minimum setup matter. Use Kotlin only if the user asks or the repo already uses it.

## GitHub Actions

Use cloud builds when the local machine lacks Android SDK/Gradle/JDK 17.

Minimum workflow:

```yaml
name: Build Android APK

on:
  workflow_dispatch:
  push:
    branches: [ main, master ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
      - uses: android-actions/setup-android@v3
      - run: sdkmanager "platforms;android-35" "build-tools;35.0.0"
      - uses: gradle/actions/setup-gradle@v4
        with:
          gradle-version: "8.7"
      - name: Build debug APK
        shell: bash
        run: |
          set -o pipefail
          gradle assembleDebug --stacktrace --info 2>&1 | tee build.log
      - uses: actions/upload-artifact@v4
        with:
          name: app-debug-apk
          path: app/build/outputs/apk/debug/app-debug.apk
      - name: Upload build log
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: build-log
          path: build.log
```

If using AndroidX, add:

```properties
android.useAndroidX=true
android.nonTransitiveRClass=true
```

## Preview-First Development

When the user wants to preview before packaging:

1. Build `preview.html` using a phone frame and realistic sample data.
2. Implement interactions that affect UI review: tabs, dialogs, empty states, list cards, sorting affordances.
3. Record design tokens in comments or a `DesignSpec` section: colors, radius, spacing, typography, card heights, and button states.
4. Implement Android UI with the same tokens in `MainActivity` or Android resources.
5. Avoid native default `Button` styling when matching a custom preview; use `TextView`/`LinearLayout` with `GradientDrawable` backgrounds or XML drawables.
6. For target SDK 35 edge-to-edge behavior, explicitly handle status bar insets. If the app is simple and preview parity matters more than Android 15 edge-to-edge, target SDK 34 is acceptable for debug/internal builds.

## Android Implementation Notes

- Use `FileProvider` for camera output and sharing private PDFs.
- Use `ACTION_OPEN_DOCUMENT` with `EXTRA_ALLOW_MULTIPLE` for gallery import.
- Use `PdfDocument` for offline image-to-PDF generation.
- Save internal app state in `SharedPreferences` JSON for small offline tools.
- Save generated files under `getFilesDir()` unless the user needs public Downloads export.
- For drag sorting, support both `startDragAndDrop` and older `startDrag`.
- Use Chinese labels directly in UTF-8 Java files; verify the file is not mojibake before committing.

## Validation

Before declaring success:

1. Compare `preview.html` against Android source for token parity: colors, radii, layout, text, and list density.
2. Push and wait for GitHub Actions to complete.
3. If build fails, download or upload `build.log`, read the actual Gradle error, fix, and re-run.
4. Download the APK artifact locally.
5. Tell the user the exact APK path and what changed.

Do not claim the APK matches the preview until the Android code has been updated from the same design spec, not merely the web preview.
