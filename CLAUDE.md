# MicroApps — project instructions

A portable monorepo of micro-apps plus a unified launcher (`AppLauncher/`),
shared across **Windows, Linux, and macOS** and across machines/users. Code,
paths, and OS checks must stay generic — a change isn't done until it would run
unchanged on someone else's box.

## Never commit machine-specific content

Before adding/editing code or committing, make sure tracked files contain none
of the following:

**1. Machine / user identity** — no usernames, home paths, hostnames, emails,
IPs, or kernel/build strings.
- ✗ `/home/alice/...`, `C:\Users\alice\...`, `host-01`, `6.0.1-fc44`
- ✓ `Path.home()`, `~`, `os.environ["HOME"]`, `%USERPROFILE%`

**2. Absolute / machine-specific directories** — resolve paths at runtime, never
hardcode one machine's layout.
- User data → `Path.home()` / XDG (`$XDG_DATA_HOME`, default `~/.local/share`).
- Temp files → `tempfile` (never a hardcoded real `/tmp/...`).
- Repo files → repo-relative via `paths.find_repo_root()` / `__file__` — not
  `/home/<you>/.../MicroApps`.
- Truly site-specific values → make them configurable (env var / `config/`),
  with a sensible default.

**3. Platform detection — generic only** — branch on OS *family*, never a distro
or an OS version.
- ✓ `sys.platform.startswith("win")`, `sys.platform == "darwin"`, else POSIX.
- ✗ `if Fedora`, `if Windows 11`, `if "fc44" in platform.release()`.
- Detect a **capability**, not a machine: `shutil.which("ptyxis")` to find a
  terminal; `sys.executable` for the interpreter (not `/usr/bin/python`).
- A genuine hard requirement (e.g. MeetingNotesOverlay needs Windows 10 build
  19041+) goes in `apps.json` `prerequisites` as a version floor — not in
  `if`-logic keyed to one machine.

**4. No personal data or secrets** — app data/state lives outside the repo
(home/XDG) and is git-ignored as defense-in-depth (e.g. TodoTUI tasks →
`~/.local/share/todo-tui/`, with `**/tasks.json` ignored). Secrets stay in the
git-ignored `config/`.

### Verify before committing

```bash
# scan only what you're about to commit
FILES=$(git diff --name-only; git ls-files --others --exclude-standard)
grep -nE '/home/|/Users/|/root/|/mnt/|[A-Za-z]:\\Users|Documents/MyGit' $FILES
grep -niE 'fedora|ubuntu|debian|windows 1[01]|fc[0-9]{2}' $FILES
grep -nE 'sys\.platform|platform\.(system|release|version)' $FILES   # must be generic
```

Every absolute-path string literal that remains should be a generic placeholder
in a test (`/work/dir`, `/fake/bin/...`) or resolved at runtime — never a real
path from your machine.

## Adding a new app

Every new app/folder must be registered in `apps.json` in the same change — see
the **add-app-to-launcher** skill. Per-app folders are PascalCase (`TodoTUI`,
`CCDashboard`); the app `id` is kebab-case.
