# Security Policy

ClaudePanes is a single-file, zero-dependency Python CLI that launches
terminal multiplexer pane layouts for Claude Code sessions. This document
covers how to report vulnerabilities and summarizes the project's threat
model. For the full threat model and design rationale, see
[docs/security.md](docs/security.md).

## Reporting a Vulnerability

If you believe you have found a security issue in ClaudePanes:

- Open a GitHub issue and apply the `security` label.
- Include a clear reproduction (TOML config, terminal adapter, OS, and the
  ClaudePanes version from `--version`).
- If the issue could be exploited against existing users, please describe
  the impact in the report so it can be triaged before broader discussion.

This is a hobby project. Response is best-effort and there are no SLAs.
Patches and reproductions are welcomed.

Note: this reporting channel may change once the project has a maintained
private security mailbox. Until then, GitHub issues with the `security`
label are the canonical channel.

## Supported Versions

Only the latest minor release receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.1.0   | Yes       |

## Threat Model Summary

The full threat model lives in [docs/security.md](docs/security.md). The
short version:

- **TOML configs are trusted-but-validated input.** ClaudePanes parses
  configs with stdlib `tomllib` (data-only, no code execution at parse
  time), enforces a strict schema, flags unknown keys, and type-checks
  every field. The user is expected to read `cmd =` strings before
  running a config from an untrusted source.
- **No network, no telemetry, no update checks.** ClaudePanes makes no
  outbound network calls. There is no remote attack surface from the tool
  itself.
- **No daemon, no IPC, no on-disk state.** ClaudePanes is a one-shot
  process. It does not create cache files, log files, sockets, or named
  pipes, so there is no cross-process attack surface and nothing for an
  attacker to plant a writable file in.
- **Command strings are passed via argv where possible, and via
  documented quoting helpers otherwise.** ClaudePanes uses
  `subprocess.run(..., shell=False)` with argv lists by default. Where a
  terminal adapter requires a composed command-line string (notably
  `wt.exe`), composition goes through `subprocess.list2cmdline` on
  Windows and `shlex.quote` on POSIX. There is no `eval`, no `exec`, no
  `os.system`, and no `shell=True`.
- **Path-typed fields are resolved relative to the config file's
  directory** and `..`-traversal that escapes the project root is
  rejected.

## Known Limitations

These are intentional non-goals. See `docs/security.md` sections 1 and 6
for the full reasoning.

- **The user is trusted to write (or audit) their own `cmd =` strings.**
  A `cmd = "rm -rf ~"` is syntactically valid TOML and will be passed
  through. ClaudePanes does not attempt to classify commands as safe or
  unsafe.
- **ClaudePanes does not sandbox the spawned shell.** Process isolation
  is the OS's job (containers, WSL2, AppArmor/SELinux, macOS sandbox
  profiles). If you want Claude Code's `/sandbox` mode, put the
  appropriate flag in your TOML's `cmd =` field.
- **ClaudePanes is not a privilege boundary.** It runs as the invoking
  user and inherits exactly that user's permissions. Do not launch it
  from an Administrator or root shell.
- **ClaudePanes does not verify terminal binary checksums.** It resolves
  `wt.exe`, `wezterm`, `tmux`, or `zellij` via `PATH` and invokes them.
  A hijacked `PATH` will be used as-is, like any other tool.

Before running a TOML config you did not write yourself, work through the
audit checklist in [docs/security.md](docs/security.md) section 8.
