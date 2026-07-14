# 8090 SoNovel Deployment

The 8090 novel module uses the upstream `freeok/so-novel` release, installed
outside Git at `/home/admin/ai/tools/so-novel/`. It does not use or modify the
legacy `/home/admin/ai/tools/sonovel-tool/` checkout.

## Runtime contract

- Pinned release: `v1.11.0` (`sonovel-linux_x64.tar.gz`), using system JDK 21
  rather than the release's bundled runtime.
- Service: `sonovel.service`, loopback only on `127.0.0.1:7765`.
- Resource limits: Java heap maximum `256M`, service memory maximum `384M`,
  at most two chapter fetches at a time.
- Lifecycle: the wrapper starts the service only for a search, packet, or
  download and stops it after that operation. A shared file lock serializes
  those operations.
- Local SoNovel output: `/home/admin/ai/tools/so-novel/downloads/`.
- 8090 archive output: `/home/admin/ai/txt/download/`.

## 8090 download behavior

The browser first searches through `/api/sonovel/search`. Search results are
kept server-side for ten minutes; a browser can only request a cached result,
not an arbitrary URL. After the user confirms they have lawful access or
processing authorization, `/api/sonovel/download` starts one global download
job. On success the server:

1. verifies the result file is inside the controlled SoNovel directory;
2. copies it to `txt/download/` without overwriting an existing filename;
3. returns an attachment URL so the open browser attempts a normal device
   download and always shows a fallback download link.

The public page has per-client search/download rate limits and polls only
while a job is active. Do not expose port 7765 directly.

## Commands

```bash
/home/admin/ai/scripts/sonovel.sh search '完整书名'
/home/admin/ai/scripts/sonovel.sh download '完整书名' '作者' txt
/home/admin/ai/scripts/sonovel.sh packet '完整书名' '官方作者'
/home/admin/ai/scripts/sonovel.sh stop
```

Only process public-domain, open-licensed, officially downloadable, or
user-authorized material. The server must not bypass paid access, logins,
DRM, captchas, or anti-bot controls.

The canonical systemd unit templates are in `systemd/sonovel.service` and
`systemd/sonovel-firewall.service`. `sonovel-control.socket` and
`sonovel-control@.service` expose only the start/stop commands needed by the
wrapper for the `admin` group. Runtime binaries, logs, locks, and downloaded
works are deliberately excluded from Git.
