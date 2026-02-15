# Deployment Runbook

This project is deployed to the Mac `clawd` instance via Git.

## Golden Rule

- Do **not** use `rsync` for deployment.
- The Mac already has a git checkout at:
  - `~/.openclaw/extensions/advanced-voice`

## Standard Deploy (Linux -> Mac)

Run from this repo on Linux:

```bash
cd /home/rleon/documents/projects/openclaw-advanced-voice
git status --short
git add .
git commit -m "your message"
git push origin master
```

Deploy on Mac by pulling latest and restarting OpenClaw:

```bash
ssh mac 'cd ~/.openclaw/extensions/advanced-voice && git pull --ff-only && openclaw gateway restart'
```

## Verify Deployment

Confirm the Mac repo is on the expected commit:

```bash
ssh mac 'cd ~/.openclaw/extensions/advanced-voice && git log --oneline -n 1'
```

Optional health checks:

```bash
ssh mac 'openclaw plugins list --json | jq ".plugins[] | select(.id == \"advanced-voice\")"'
ssh mac 'openclaw gateway status'
```

## Fast One-Liner

If changes are already committed locally:

```bash
git push origin master && ssh mac 'cd ~/.openclaw/extensions/advanced-voice && git pull --ff-only && openclaw gateway restart'
```

## Rollback

If a bad deploy lands:

1. On Linux, revert or fix and push a new commit (preferred).
2. If immediate rollback is needed on Mac:

```bash
ssh mac 'cd ~/.openclaw/extensions/advanced-voice && git reflog -n 5'
ssh mac 'cd ~/.openclaw/extensions/advanced-voice && git reset --hard <previous-good-commit> && openclaw gateway restart'
```

Use hard reset only for emergency rollback, then reconcile history properly from the main repo.

## Troubleshooting

- `git pull --ff-only` fails:
  - Mac has local changes. Inspect and clean/stash there before pulling.
- Plugin not loading after restart:
  - Check restart output and plugin list.
- Wrong host:
  - SSH alias used by this runbook is `mac` (from `~/.ssh/config`).
