---
name: session-vault
description: Back up and restore native local sessions for Codex, Claude Code, Hermes, Pi and CodeBuddy CLI, plus CodeBuddy CN IDE conversations exported as JSON/ZIP. Back up non-sensitive ZCode profile files only. Use for local session migration and verified recovery; Qoder, WorkBuddy, TRAE and web-chat histories are not supported.
---

# Session Vault

Run `python3 scripts/session_vault.py --help` relative to this skill on macOS/Linux; on Windows use `py -3 scripts/session_vault.py --help` (or `python` if it launches Python 3). Standard library only; Python 3.9+. No third-party install required.

## Scope and workflow

1. For a backup request, default to the current agent only: back up that agent's sessions and its supported non-sensitive memory, rules, skills and settings. Before running, tell the user other supported agents are available and ask whether to include any; include only the agents the user selects. Never silently expand a current-agent backup to every detected agent. Respect CODEX_HOME, CLAUDE_CONFIG_DIR, HERMES_HOME, PI_CODING_AGENT_DIR, CODEBUDDY_CONFIG_DIR, CODEBUDDY_CN_EXPORTS, ZCODE_HOME and explicit overrides. Session adapters cover Codex, Claude Code, Hermes, Pi, CodeBuddy CLI, and CodeBuddy CN IDE exports. ZCode is profile-only; Qoder, WorkBuddy and TRAE have no session adapter. CodeBuddy CN IDE sessions enter the archive through its official JSON/ZIP export; do not copy its application database because it also stores credentials. ZCode contributes only explicitly whitelisted global configuration, rules, agents, skills and commands; its device credentials and telemetry identity are excluded. Ask only if the backup location cannot be inferred. Keep all snapshots and content-addressed objects under that one root.
2. Back up first. This reads native files and uses SQLite's online backup API. A source file changing during read aborts the backup rather than silently truncating it. Every object is SHA-256 checked and atomically written; the manifest and current-head pointer are atomically replaced only after every referenced object, JSONL transcript, SQLite `quick_check`, and required table passes verification. A failed or partial snapshot never replaces the current verified head. For coherent multi-file sessions prefer agents idle; a SQLite snapshot and a transcript read are not an atomic cross-file snapshot. A missing rollout is a warning and blocks promotion.
3. Show `TREE.md`, `index.html`, source presence, excluded credential files, and warnings/counts. Display the stored session name, falling back to the stored title, preview, or first user message before using an ID. Keep IDs in metadata and expandable details, not as the primary session label. Snapshots stay immutable and separate by host. The current head only moves after full verification. On a receiving computer, use `--snapshot latest --host SOURCE_HOST`; this scans newest to oldest and selects the newest fully verified snapshot, so an incomplete cloud copy falls back to A.
4. **Default to browser-based restore planning.** For a restore request, run `restore-ui`; it starts a temporary server bound to `127.0.0.1` and opens the local comparison page automatically. Use the browser-control tool when available to operate the page: review readable source sessions on the left, set destinations on the right, select sessions, and export the plan. Do not stop after merely opening the page; continue through plan preview and restore once the selected sessions and destinations are clear. On macOS the page has native “选择目录” buttons; on Windows, drive-letter paths are accepted and editable. After the plan is downloaded, stop the local server with Ctrl+C. The page is the planning interface; `restore --plan` verifies the entire snapshot before applying. If Codex's embedded browser shows a blank page for a `file://` link, use the local `http://127.0.0.1` URL printed by `restore-ui`; the raw `assets/restore-ui.html` is a template, not a populated planner. If browser control is unavailable, leave the opened page ready for the user rather than silently switching to CLI. If the user explicitly asks to avoid browser operations, skip the page and use CLI restore options directly; `restore-ui --no-web` creates an offline page without opening a browser. IDs stay inside the plan for exact matching. CLI users can select `--project`, provider, or `--session`, and map source directory prefixes with repeated `--map OLD=NEW` (longest prefix wins).
5. Restore defaults to dry-run. Initialize a compatible target agent before database restore. Refuse unknown schemas or existing session IDs rather than replace target state. `--restore-profile` separately restores archived memories, rules, skills, and non-sensitive settings; credential files and files containing credential-like values are excluded, and existing different destination files cause an error instead of overwrite. Preserve the original Codex `title`; when `name` is empty, fill it from the stored display title so the imported row still has a human-readable label. Optional `--name-prefix` affects the Codex display name only. On apply, target agents must be closed; never stop running conversations without the user's agreement. Save an atomically written SQLite pre-restore snapshot, transactionally merge rows, and preserve existing unrelated sessions. A failed restore can leave copied rollouts unindexed; keep the archive and diagnose before retrying. After import restart the agent, inspect its session list, and verify one resumed conversation. Do not call restoration verified merely because files copied.

## Commands

```bash
# In the skill workflow, back up the current agent only by default. Repeat --provider to include more agents.
python3 scripts/session_vault.py backup --vault '/path/to/session-backups' --host macbook --provider codex

# Back up several explicitly selected providers.
python3 scripts/session_vault.py backup --vault '/path/to/session-backups' --host macbook \
  --provider codex --provider hermes --provider pi

# CodeBuddy CN IDE: export JSON/ZIP files into a dedicated folder, then include it in backups.
python3 scripts/session_vault.py backup --vault '/path/to/session-backups' \
  --provider codebuddy-cn --codebuddy-cn-exports '/path/to/CodeBuddy CN exports'

# Check the newest complete source snapshot on the receiving computer.
# --ack writes a receipt that syncs back to the source.
python3 scripts/session_vault.py verify --vault '/path/to/session-backups' \
  --snapshot latest --host macbook --ack

# Install a recurring background task. Frequency defaults to 15 minutes.
python3 scripts/session_vault.py schedule install --vault '/path/to/session-backups'
python3 scripts/session_vault.py schedule install --vault '/path/to/session-backups' --minutes 30
python3 scripts/session_vault.py schedule install --vault '/path/to/session-backups' \
  --codebuddy-cn-exports '/path/to/CodeBuddy CN exports'
python3 scripts/session_vault.py schedule status
python3 scripts/session_vault.py schedule remove

# CLI-only migration if the user explicitly requests no browser interaction.
python3 scripts/session_vault.py restore --vault '/path/to/session-backups' \
  --snapshot '/path/to/session-backups/snapshots/macbook/SNAPSHOT' \
  --project '/old/projects/merchant' --map '/old/projects=/new/projects'

# Default restore planning opens the local browser page automatically.
python3 scripts/session_vault.py restore-ui --vault '/path/to/session-backups' \
  --snapshot latest --host macbook \
  --output '/path/to/restore-plan.html'

# Explicitly skip opening a browser; write a static planner instead.
python3 scripts/session_vault.py restore-ui --vault '/path/to/session-backups' \
  --snapshot '/path/to/session-backups/snapshots/macbook/SNAPSHOT' \
  --output '/path/to/restore-plan.html' --no-web

# Preview and apply the downloaded plan without typing session IDs.
python3 scripts/session_vault.py restore --plan '/path/to/session-vault-restore-plan.json'
python3 scripts/session_vault.py restore --plan '/path/to/session-vault-restore-plan.json' \
  --apply --agents-stopped
# CodeBuddy CN restore writes a validated native-import ZIP to the selected folder.
# Then import it in CodeBuddy CN from History. Native import was not verified while the app was signed out.
python3 scripts/session_vault.py restore --plan '/path/to/session-vault-restore-plan.json' \
  --codebuddy-cn-home '/path/to/CodeBuddy CN Imports' --apply --agents-stopped
python3 scripts/session_vault.py restore --vault '/path/to/session-backups' \
  --snapshot '/path/to/session-backups/snapshots/macbook/SNAPSHOT' \
  --restore-profile --apply --agents-stopped
python3 scripts/session_vault.py restore --vault '/path/to/session-backups' \
  --snapshot '/path/to/session-backups/snapshots/macbook/SNAPSHOT' \
  --provider codex --session UUID --map '/old/projects=/new/projects' --name-prefix 'Imported-' \
  --apply --agents-stopped

# Explicit auxiliary artifact, excluded unless requested. Repeat for individual files.
python3 scripts/session_vault.py backup --vault '/path/to/session-backups' \
  --include '/old/project/report.md'
# Restore extras only on explicit request: --restore-extras plus destination path mapping.
```

This skill does not provide cloud backup or sync. It only writes to the folder you specify; use Nutstore, iCloud, Huawei Cloud, Tencent Weiyun or another sync tool yourself to copy that folder. Keep the archive private: conversation transcripts can contain credentials, source code and tool output. The configured memory, rules, skills and non-sensitive settings are backed up; credential files and profile files with detected credential-like values are excluded. Credentials already present inside conversation text remain part of the native transcript. CodeBuddy CN IDE's scheduled snapshots only include exports already saved in the configured export folder; the IDE does not expose a supported background export command. Its settings and login state are not copied.

For recurring backups, recommend installing a background task after the first successful manual backup. If the user requests a recurring task but gives no frequency, use 15 minutes. `schedule install` uses a per-user macOS LaunchAgent or Windows Task Scheduler task, avoids overlapping runs, writes logs into the archive, and can be checked or removed with the commands above. Do not install it merely because a one-off backup was requested. The archive itself still needs the user's cloud sync client.

The public cloud-client documentation reviewed here describes sync status in each vendor's UI, but does not provide a common supported API for this skill to query whether every file in an arbitrary folder has synced. The receiving computer can run `verify --ack` only after hashes, JSONL, and native SQLite snapshots pass. That receipt syncs back with the archive; the next source backup may then remove older snapshots and unreferenced objects while retaining the verified current head. Without a receipt, old snapshots remain. This is an archive-to-archive proof, not a cloud-vendor status check.

## Native preservation and limits

Read [references/native-layout.md](references/native-layout.md) for adapter coverage and recovery limitations. Pi, CodeBuddy CLI, CodeBuddy CN exports, and ZCode profile migration are fixture-tested; the CodeBuddy CN app was signed out during this machine's check, so its native import and conversation continuation remain unverified. Do not promise complete desktop UI fidelity or compatibility with untested future schemas. GPT here means local Codex CLI/App sessions, Claude means Claude Code; cloud-only ChatGPT/Claude chats require separate exports.

Intermediate artifacts means separate workspace files, tool caches, builds, screenshots and shell snapshots; they are excluded by default. Tool messages, reasoning and subagent transcripts inside native session history are preserved, because stripping them can break continuation. `--include` accepts explicit files only and never recursively sweeps project directories.
