# Novel Actions

Private GPT Action backend for the local Fanqie novel workflow.

## Local endpoints

- Service: `http://127.0.0.1:8091`
- OpenAPI: `/openapi.json`
- Privacy: `/privacy`
- Public Action origin: `https://iz5ts314xq7lzp4t07pfmoz.tail04405f.ts.net`

All `/v1/*` endpoints require `Authorization: Bearer <action.token>`.

The production token and SQLite state are stored in
`/home/admin/ai/runtime/novel-actions/`. The token file is mode `600` and is
not printed in logs.

## Runtime

```bash
systemctl status novel-actions.service
journalctl -u novel-actions.service -n 100 --no-pager
```

The service deliberately has no publishing endpoint.

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
