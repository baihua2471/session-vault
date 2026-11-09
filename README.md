# Session Vault

Back up and restore supported coding-agent sessions and non-sensitive agent profiles to a folder you choose. Snapshots are verified before the current backup pointer advances, and the restore planner lets you review source sessions and destination paths before applying a restore.

## Supported agents

| Agent | Coverage | Recovery boundary |
| --- | --- | --- |
| Codex | Local Codex app/CLI sessions and whitelisted profile files | Compatible local Codex storage; check the native-layout reference for schema limits. |
| Claude Code | CLI sessions, subagent transcripts and whitelisted rules, skills, commands, agents and project memory | Claude Code local files; Claude web-chat history is not included. |
| Hermes | `state.db` session data and whitelisted profile files | SQLite snapshot and session rows; initialize the same profile/schema before restore. |
| Pi | JSONL sessions and whitelisted global profile files | Fixture-verified; a real restored session still needs a native resume check. |
| CodeBuddy Code CLI | JSONL sessions and screened profile files | Fixture-verified; remapped project-picker indexing is not guaranteed. |
| CodeBuddy CN IDE | Official JSON/ZIP conversation exports | Backup requires exports already saved to a folder; restore creates an import ZIP for the IDE History page. App settings, login state and global memories are not included. |
| Z.ai ZCode | Non-sensitive global configuration, `AGENTS.md`, agents, skills and commands | Profile-only. Session history, credentials and device telemetry identity are excluded. |

**Not supported:** Qoder, WorkBuddy, TRAE, ChatGPT web chats and Claude web chats. Qoder may be revisited through its SDK session-storage integration; WorkBuddy and TRAE remain deferred.

See [`references/native-layout.md`](references/native-layout.md) for native storage formats, evidence and per-agent limitations.

## Install

Clone this repository into a Codex skills directory, then restart or refresh Codex:

```bash
git clone https://github.com/baihua2471/session-vault.git ~/.codex/skills/session-vault
```

Python 3.9+ is required; the scripts use only the Python standard library.

## Quick start

```bash
python3 ~/.codex/skills/session-vault/scripts/session_vault.py backup \
  --vault '/path/to/session-backups' --host my-computer

python3 ~/.codex/skills/session-vault/scripts/session_vault.py verify \
  --vault '/path/to/session-backups' --snapshot latest --host my-computer

python3 ~/.codex/skills/session-vault/scripts/session_vault.py restore-ui \
  --vault '/path/to/session-backups' --snapshot latest --host my-computer
```

Restore defaults to a dry run. Review the plan and selected destination paths before applying it. The recurring backup task defaults to every 15 minutes when no interval is provided; macOS LaunchAgent and Windows Task Scheduler are supported.

## Storage and privacy

- This skill writes to the folder you specify; it does not provide cloud storage or cloud sync. Use your own sync tool for the archive folder.
- Back up the skill source code only. Never commit backup snapshots, exported conversations, session databases, or real agent state to this repository.
- Credentials and credential-like profile settings are excluded. Credentials already present in a conversation transcript remain part of that transcript.
- CodeBuddy CN scheduled snapshots only include exports already present in the configured export folder; the IDE does not expose a supported background export command.

## Validate

```bash
python3 -B scripts/test_session_vault.py
```

The fixture suite covers session providers, profile exclusions, snapshot integrity, restore planning and native import bundle generation. Fixture success does not replace a native restore/resume check in each agent application.
