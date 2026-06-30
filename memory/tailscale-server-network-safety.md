# Tailscale server network safety

- On 2026-06-30, initial `tailscale up` caused this server's existing public
  connection to become unreachable.
- The recovered production configuration uses `NetfilterMode: off`, no exit
  node, `RouteAll: false`, `RunSSH: false`, and no advertised routes.
- Never run a bare `tailscale up` on this machine after enrollment. It may
  reapply defaults and disrupt public SSH/nginx/xray access.
- Preserve the current configuration. Inspect it with `tailscale debug prefs`.
  Use narrowly scoped `tailscale set` commands only when a preference must
  change.
- The GPT Action is exposed with `tailscale funnel --bg 8091`; Funnel itself
  does not require changing route or netfilter preferences.
- A known-good preference snapshot is stored at
  `/home/admin/ai/runtime/novel-actions/tailscale-prefs-safe.txt`.
