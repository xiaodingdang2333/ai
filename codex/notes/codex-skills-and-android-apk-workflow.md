# Codex Skills 同步与安卓 APK 制作流程

这份文档记录 2026-05-25 搭建好的流程。以后在另一台电脑上使用 Codex 时，即使看不到这次聊天记录，也可以根据本文继续使用。

## 已经完成的设置

Codex 的 skills 现在通过这个 Git 仓库同步：

```text
D:\ai
```

同步后的 skills 根目录是：

```text
D:\ai\codex\skills
```

在当前电脑上，Codex 默认读取的 skills 目录：

```text
%USERPROFILE%\.codex\skills
```

已经通过 Windows junction 指向：

```text
D:\ai\codex\skills
```

也就是说，以后在本机创建或安装 skill，实际文件都会写入 `D:\ai\codex\skills`，可以通过 Git 同步到另一台电脑。

## 另一台电脑怎么使用

### 1. 拉取 ai 仓库

如果另一台电脑还没有 `D:\ai`：

```powershell
git clone git@github.com:xiaodingdang2333/ai.git D:\ai
```

如果已经有 `D:\ai`：

```powershell
cd D:\ai
git pull
```

### 2. 运行 skills 链接脚本

```powershell
powershell -ExecutionPolicy Bypass -File D:\ai\codex\link-codex-skills.ps1
```

这个脚本会做三件事：

1. 备份另一台电脑原来的 `%USERPROFILE%\.codex\skills`
2. 创建 junction
3. 让 Codex 默认 skills 目录指向 `D:\ai\codex\skills`

### 3. 重启 Codex

运行脚本后，需要重启 Codex。重启后 Codex 就会从 `D:\ai\codex\skills` 读取 skills。

## 重要 Skill：安卓 APK 制作

本次创建的安卓 App 制作 skill 是：

```text
D:\ai\codex\skills\android-apk-builder
```

以后你想让我做这些事情时，会用到这个 skill：

- 创建安卓 App
- 生成 APK 安装包
- 做单机离线 App
- 做拍照、相册、文件、PDF 类工具
- 用 GitHub Actions 云端打包 APK
- 先在 Codex/浏览器里预览界面，满意后再打包
- 要求网页预览效果和手机安装后的 APK 效果一致

这个 skill 最重要的规则是：

> 网页预览就是 APK 界面的合同。不能只把 `preview.html` 做得好看，Android 真机界面也必须按同一套颜色、圆角、间距、字体和布局规则实现。

更详细的预览一致性规则在：

```text
D:\ai\codex\skills\android-apk-builder\references\preview-parity.md
```

## 这次安卓 APK 的制作流程

以“照片转 PDF 整理”App 为例，本次流程是：

1. 本地创建原生 Android Java 项目
2. 创建 `preview.html`，用于在 Codex/浏览器里先看界面
3. 配置 GitHub Actions，让 GitHub 云端打包 APK
4. 把项目推送到 GitHub
5. 读取 Actions 构建状态和日志
6. 修复构建失败问题
7. 下载 `app-debug.apk`
8. 手机安装测试
9. 根据手机截图对比网页预览
10. 修改 Android 真机 UI，让它尽量和网页预览一致
11. 重新打包 APK

这次安卓项目的 GitHub 仓库是：

```text
git@github.com:xiaodingdang2333/PhotoPdfOrganizer.git
```

当前电脑上的项目目录是：

```text
C:\Users\小叮当\PhotoPdfOrganizer
```

本次最后生成的新版 APK 路径是：

```text
C:\Users\小叮当\PhotoPdfOrganizer-apk-preview-ui\app-debug.apk
```

## GitHub Actions 打包方式

如果本地电脑没有 Android SDK、Gradle、JDK 17，就不要硬装一大堆环境，优先使用 GitHub Actions 云端打包。

推荐的 Actions 流程：

- 使用 `actions/setup-java@v4`
- 使用 Temurin JDK 17
- 使用 `android-actions/setup-android@v3`
- 用 `sdkmanager` 安装 Android platform 和 build tools
- 使用 Gradle 8.7
- 执行 `gradle assembleDebug --stacktrace --info`
- 上传 APK 产物
- 不管成功失败，都上传 `build.log`

一定要上传 `build.log`，因为 GitHub 页面有时只显示 `exit code 1`，看不到真正的 Gradle 错误。

## 以后如何同步新的 skill

以后如果创建、修改、安装了 skill，在本机执行：

```powershell
cd D:\ai
git status
git add codex
git commit -m "Update Codex skills"
git push
```

然后另一台电脑执行：

```powershell
cd D:\ai
git pull
```

就能同步过去。

当前仓库的 `.gitignore` 已经排除了 Python 缓存文件：

```text
__pycache__/
*.pyc
```

## 关于聊天记录

Codex 的聊天记录不一定会跟着 `D:\ai` 同步。

也就是说，另一台电脑登录 Codex 后，可能能看到历史对话，也可能看不到，这取决于 Codex 账号和云端历史同步能力。

所以不要依赖聊天记录来恢复上下文。以后主要依赖这几样东西：

- `D:\ai\codex\notes` 里的说明文档
- `D:\ai\codex\skills` 里的 skills
- GitHub 上的项目仓库
- GitHub Actions 的构建记录
