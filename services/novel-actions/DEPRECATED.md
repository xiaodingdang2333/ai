# Deprecated

This custom GPT Action service is deprecated for novel production.

Do not use it for new web ChatGPT writing, sample teardown, chapter revision, or
Fanqie upload workflows.

Current direction:

- Web ChatGPT writes through the Git-based workflow in
  `/home/admin/chatgpt-novel-production-system`.
- Server scripts scan Git queue files for sample acquisition and upload work.
- Server Codex may perform packet-level deep teardown only when explicitly
  requested by a Git sample request.
- Fanqie draft upload should be triggered from Git project readiness, not from
  this Action API.

The directory is kept only as historical code until a separate cleanup removes
or archives it safely.

