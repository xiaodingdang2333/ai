# Novel Actions

Private GPT Action backend for the local Fanqie novel workflow.

## Local endpoints

- Service: `http://127.0.0.1:8091`
- OpenAPI: `/openapi.json`
- Privacy: `/privacy`
- Public Action origin: `https://iz5ts314xq7lzp4t07pfmoz.tail04405f.ts.net`

The systemd unit must use `NoNewPrivileges=false`: the service runs as `admin`, while the fixed Fanqie Snap cache switch/save commands require `sudo -n` to access root-owned Chromium profiles. Account names and ports remain server-side allowlisted.

All `/v1/*` endpoints require `Authorization: Bearer <action.token>`.

The production token and SQLite state are stored in
`/home/admin/ai/runtime/novel-actions/`. The token file is mode `600` and is
not printed in logs.

## Runtime

```bash
systemctl status novel-actions.service
journalctl -u novel-actions.service -n 100 --no-pager
systemctl status sonovel-cache-cleanup.timer
```

The service deliberately has no publishing endpoint.

Market study jobs use resource-aware concurrency: 3 workers when memory and
load allow, otherwise 2 or 1. Action calls long-poll for at most 35 seconds,
while each SoNovel batch is bounded to 90 seconds. Successful packets are
reused for 30 days. The daily 02:30 cleanup removes stale selected chapters
after 90 unused days but retains indexes and analysis notes.

## Tailscale network safety

This server must keep Tailscale `NetfilterMode: off`; otherwise its existing
public SSH and web services may become unreachable. Do not run a bare
`tailscale up` again. Inspect with `tailscale debug prefs`, and change only an
individual setting with `tailscale set` when necessary. Funnel is managed only
with:

```bash
tailscale funnel --bg 8091
tailscale funnel status
```

## Verification

```bash
python3 tests/smoke.py
python3 -m json.tool openapi.json >/dev/null
```
