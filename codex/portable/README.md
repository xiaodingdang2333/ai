# Codex Portable Snapshot

This directory makes the repository usable as a Codex migration source for a
second Linux server.

It contains:

- `system-skills/`: the exact built-in skill files present at snapshot time.
- `plugins/`: installed plugin bundles and their install metadata.
- `private-state.tar.zst.enc`: encrypted Codex sessions, prompt history,
  configuration, rules, goals, memories, and state databases.
- `memory/root-machine/`: shared machine memory restored to `/root/ai/memory`.
- `snapshot.sh`: refreshes the portable snapshot from the current machine.
- `restore.sh`: restores it into another user's `$CODEX_HOME`.

Credentials are deliberately excluded: `auth.json`, API keys, browser
profiles/cookies, shell snapshots, installation IDs, logs, caches, downloaded
Codex binaries, and live service tokens are not copied. After restoration,
run `codex login` and configure provider API keys in the new server's
environment.

## Restore on another server

```bash
git clone https://github.com/xiaodingdang2333/ai.git ~/ai
cd ~/ai
export CODEX_ARCHIVE_PASSPHRASE='the separately stored passphrase'
bash codex/portable/restore.sh
```

The restore script backs up conflicting destination files, restores encrypted
history/state, installs the snapshotted plugin and system-skill files, and
creates symlinks for workspace skills under `codex/skills/`.

The encrypted archive is safe to keep in the public repository only while the
passphrase remains outside Git. Never commit the passphrase.
