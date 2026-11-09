# Session Vault

**Moving to a new computer or recovering after a machine failure? Keep your AI coding work with you.** Session Vault turns agent conversations and non-sensitive profile files stored across different local formats into verified snapshots in a folder you control. Its browser planner lets you recognize sessions by name, choose which ones to restore, and map old project paths to their new destinations.

**换电脑、电脑故障，或者临时换一台电脑继续工作时，不必从一堆 ID 和 agent 私有目录里手工拼回历史。** Session Vault 把不同 coding agent 的会话与非敏感配置备份成可校验的快照；恢复时用浏览器界面查看会话名称、原项目路径和目标路径，再逐个选择要恢复的内容。

## A typical migration / 典型迁移场景

Imagine your main computer stops working and you move to a temporary one. Codex, Claude Code, Hermes, Pi and CodeBuddy each keep history differently. The temporary computer may also use different project paths, and a cloud sync may have copied only part of the newest backup.

1. On the old computer, save snapshots to a folder you choose. You can schedule recurring backups; the default interval is 15 minutes.
2. Sync that folder with your own cloud client, such as iCloud or Nutstore. Session Vault does not provide cloud storage or read a provider's sync-complete indicator.
3. On the receiving computer, verify the archive. `--snapshot latest` selects the newest snapshot whose referenced files, transcripts and supported databases pass validation; an incomplete newer snapshot is skipped when an older verified snapshot is available.
4. Open the restore planner. It shows readable session labels and original workspaces beside destination folders. Select only the sessions you need, map old project paths to new ones, review the dry run, then apply.
5. Restore supported agent memories, rules, skills and non-sensitive settings separately when needed. Credential files are excluded.

举例：主力电脑坏了，你先用临时电脑继续同一个项目。不同 agent 的会话格式各不相同，项目目录也可能换了位置；云盘可能只同步到了最新一份备份的一部分。Session Vault 会在接收电脑上校验快照，优先选完整可用的一份，再用恢复界面按会话名称挑选记录并为每个项目指定新目录。若没有完整快照，它会停下来报告错误，不把半份会话当成成功恢复。

This is useful when migrating between machines, continuing work from a temporary computer, consolidating histories from several agents, or recovering from an interrupted backup sync. It does not make a partially transferred snapshot complete; if no fully verified snapshot arrived, restore stops and reports that.

## What it protects

- **Verified snapshots:** objects are hash-checked, supported JSONL transcripts are validated, and SQLite snapshots are checked before the current verified head advances. A failed or partial local backup does not replace the previous verified head.
- **Recoverable history:** compatible native session stores are restored without replacing unrelated target sessions. Existing session IDs and schema conflicts are reported for review.
- **Readable, path-aware restore:** the planner helps identify sessions by their stored name/title or first user message, then assign destinations per session without typing IDs.
- **Safer profile migration:** whitelisted memories, rules, skills and non-sensitive settings can be restored separately; credential files and credential-like settings are excluded.
- **Recurring backups:** macOS LaunchAgent and Windows Task Scheduler are supported. When no interval is specified, the schedule defaults to every 15 minutes.

## Supported agents

| Agent | Coverage | Recovery boundary |
| --- | --- | --- |
| Codex | Local Codex app/CLI sessions and whitelisted profile files | Compatible local Codex storage; see the native-layout reference for schema limits. |
| Claude Code | CLI sessions, subagent transcripts and whitelisted rules, skills, commands, agents and project memory | Claude Code local files; Claude web-chat history is not included. |
| Hermes | `state.db` session data and whitelisted profile files | SQLite snapshot and session rows; initialize the same profile/schema before restore. |
| Pi | JSONL sessions and whitelisted global profile files | Fixture-verified; a real restored session still needs a native resume check. |
| CodeBuddy Code CLI | JSONL sessions and screened profile files | Fixture-verified; remapped project-picker indexing is not guaranteed. |
| CodeBuddy CN IDE | Official JSON/ZIP conversation exports | Export files must already exist; restore creates an import ZIP for the IDE History page. App settings, login state and global memories are not included. |
| Z.ai ZCode | Non-sensitive global configuration, `AGENTS.md`, agents, skills and commands | Profile-only. Session history, credentials and device telemetry identity are excluded. |

**Not supported:** Qoder, WorkBuddy, TRAE, ChatGPT web chats and Claude web chats. See [`references/native-layout.md`](references/native-layout.md) for formats, evidence and per-agent limits.

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

Restore defaults to a dry run. Review the selected sessions and destinations before applying it. For CodeBuddy CN IDE, export conversations to JSON/ZIP before backup and import the generated ZIP from the IDE's History page after restore.

## Storage and privacy

- Session Vault only writes to the folder you specify. It does not provide cloud backup or sync; configure your own cloud client for that folder.
- Session Vault does not query a cloud client's sync-complete status. Verify the archive on the receiving computer before restoring.
- Back up the skill source code only. Never commit backup snapshots, exported conversations, session databases or real agent state to this repository.
- Credential files and profile settings with credential-like values are excluded. Credentials already inside conversation transcripts remain untouched.
- CodeBuddy CN scheduled backups only include exports already saved in the configured folder; the IDE does not expose a supported background export command.

## Validate

```bash
python3 -B scripts/test_session_vault.py
```

The fixture suite covers session providers, profile exclusions, snapshot integrity, restore planning and native import bundle generation. Fixture success does not replace a native restore/resume check in each agent application.
