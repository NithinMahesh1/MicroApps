# ClaudePanes FAQ

Short answers to recurring questions. Each entry cross-references the
authoritative doc or ADR; treat those as canonical when this file drifts.

---

**Q: Why not just script `wt.exe` directly in a `.ps1` or `.cmd` file?**

A: You can — and for a one-off layout that is the right tool. ClaudePanes
exists for layouts you want to (a) check into a repo as data, (b) reuse
across different terminals (`wt`, `wezterm`, `tmux`, `zellij`), and
(c) keep portable across teammates who may not have your shell. The TOML
layout is terminal-agnostic; the adapter layer (ADR-006 in
`docs/design-decisions.md`) translates one config into whichever multiplexer
is on PATH. A `wt.exe` script is locked to one terminal on one OS.

---

**Q: Why no daemon or persistent state?**

A: ADR-010 (`docs/design-decisions.md`). A daemon would add a socket to
secure, recovery semantics to design, PID files, autostart entries, and a
lifecycle bug surface — all to re-implement state the host terminal already
tracks. ClaudePanes reads the config, spawns the layout, exits. ADR-011
extends this: `start` is fire-and-forget; the spawned multiplexer owns
every pane's lifecycle from that point on.

---

**Q: Why TOML and not YAML or JSON?**

A: ADR-004. TOML parses via stdlib `tomllib` (Python 3.11+), which is why
ADR-002 sets that as the version floor. YAML needs PyYAML, violating
ADR-003 (zero third-party deps), and `yaml.load` has a CVE history around
arbitrary object construction. JSON has no comments and gets noisy fast
for nested tables. TOML is data-only by construction — there is no code
path that would `exec` the file.

---

**Q: Why a single-file Python script and not a proper package?**

A: ADR-005. The whole tool is "read TOML, pick adapter, build command,
spawn process." A new contributor or security auditor can read
`claude_panes.py` end-to-end in roughly fifteen minutes. ADR-005 sets the
trigger for splitting into a package: roughly 800 lines, or when the
adapter set explodes. We are not there.

---

**Q: Why zero third-party runtime dependencies?**

A: ADR-003. The audit surface is "Python stdlib plus our one source file"
— that's it. No `requirements.txt`, no lockfile, no Dependabot pings, no
supply-chain surprises. The cost is hand-writing a few things a library
would give us (argparse help text, validation errors). For our five-field
schema that trade is overwhelmingly in our favor.

---

**Q: Can ClaudePanes broadcast input to all panes at once?**

A: No, and it will not. `broadcast_input` is listed under "Out of scope"
in `PROGRESS.md` (the explicitly-deferred section) and in
`docs/config-format.md` §future-fields as a non-goal. Both tmux and
WezTerm provide built-in broadcast via their own key bindings — use those.

---

**Q: How does this relate to `claude agents` / `claude --bg` background sessions?**

A: They are complements, not competitors. See
`docs/related-claude-features.md`. Background sessions are best for
fire-and-forget tasks that should survive a closed terminal (PR review,
"babysit CI"). ClaudePanes is best when you want N live Claude sessions
visible side-by-side in real panes with per-pane WSL distro or working
directory. One pane in a ClaudePanes layout can itself host the
`claude agents` dispatch TUI.

---

**Q: Does ClaudePanes sandbox or isolate the child Claude sessions?**

A: No. ADR-008 and ADR-009. Sandboxing is delegated entirely to Claude
Code's own `/sandbox` running inside WSL2; ClaudePanes' only contribution
is letting your per-pane `cmd` take the shape `wsl.exe -d <distro> -- claude`
so the sandboxed environment is available. ClaudePanes never claims
isolation and explicitly stays out of permission-allowlist territory
(ADR-009; see `docs/permission-allowlist.md`).

---

**Q: Does it support macOS Terminal.app, iTerm2, Hyper, Alacritty, Kitty, or cmder?**

A: Not as direct adapters. v0.1.0 supports only the four listed in the
README: Windows Terminal, WezTerm, tmux, Zellij. The reason is
ADR-006: each adapter is a non-trivial CLI-shape integration, and we only
ship adapters we use. Users on macOS who want panes can run tmux (works
natively) or WezTerm; on iTerm2 you can run tmux inside it. Adding a new
adapter is "one class plus one registry entry" per ADR-006 if you want to
contribute one.

---

**Q: How do I use ClaudePanes inside WSL?**

A: For the tmux adapter on Windows you **must** invoke ClaudePanes from
inside a WSL session. ADR-013 explains why: tmux has no native Windows
port, and auto-wrapping with `wsl.exe -- tmux ...` would force ClaudePanes
to pick a distro name and login-shell behavior — exactly the policy
decisions ADR-008 keeps in the user's hands. Consequence: `claude-panes
detect` on native Windows will not list tmux. That's the correct signal,
not a bug.

---

**Q: Can I have different layouts per project?**

A: Yes. Layouts are just TOML files; pass the path explicitly:
`claude-panes start ./my-project-layout.toml`. The CLI (see
`docs/cli-spec.md` §2.1) accepts either a bare layout name (resolved
against `~/.config/claude-panes/layouts/`) or a path to any `.toml` file.
Check the layout into the repo and teammates with ClaudePanes installed
get the same panes.

---

**Q: Why does `validate` only report one error at a time?**

A: This was Q4 in `PROGRESS.md`'s Decisions log, resolved 2026-05-20:
v0.1.0 fails fast on the first error. `docs/cli-spec.md` §2.3 documents
the behavior: "On the first validation error, `validate` prints the error
to stderr and exits with code `2`. Multi-error aggregation is not
implemented in v0.1.0." Roadmap-wise this is deferred to Phase 3 in
`PROGRESS.md`. Fix the printed error and re-run.

---

**Q: What's the difference between top-level `[[panes]]` and `[[tabs.panes]]`?**

A: `[[panes]]` describes a single-tab layout — one tab with N panes
(`docs/config-format.md` §3). `[[tabs]]` describes a multi-tab layout
where each tab has its own `[[tabs.panes]]` array with **exactly the same
pane schema** (§4 and §5.4). The two are mutually exclusive — a file with
both is a validation error (§6). Inside `[[tabs.panes]]`, `parent` indices
are scoped to that tab; you cannot reference panes in other tabs.

---

**Q: Can I use environment variables inside `cmd`?**

A: Not via ClaudePanes itself. Per `docs/config-format.md`, the `~` and
`$VAR` / `%VAR%` expansion ClaudePanes performs is applied to
`working_dir` only (top-level and per-pane). `cmd` is passed to the
multiplexer as a literal string — quoting is the config author's job
(§5.3 `panes.cmd`). If you want env expansion in the command, let the
shell do it: write `cmd = "bash -lc 'echo $MY_VAR && claude'"` so `bash`
expands `$MY_VAR` at run time, not at TOML-parse time.

---

**Q: Why does relaunching the same tmux layout open a brand-new session every time?**

A: By design, post-bugfix (2026-05-20 sweep in `PROGRESS.md`). Without a
unique name, `tmux new-session -s <name>` would error or attach to the
existing session and graft new splits onto it — almost never what you
want. ClaudePanes appends a millisecond timestamp:
`{layout.name}-{ms_timestamp}` (e.g. `feature-x-1716192345123`). See
`docs/terminal-adapters.md` (tmux section, around the
"`new-session` mapping" table and the "fresh session name" paragraph).
Each relaunch is a clean session; nothing gets grafted onto a stale one.
