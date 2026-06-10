# Permission Allowlist for Claude Code

## What this doc is

This is a configuration recipe for **Claude Code**, not for ClaudePanes itself. It addresses a related workflow problem: yes-fatigue when Claude Code prompts for permission on every read-only command (`ls`, `pwd`, `cat`, `grep`, `git status`, etc.).

ClaudePanes does not modify Claude Code's settings. You apply the changes in this doc manually to `~/.claude/settings.json` (or a project-local file). The two efforts are independent but solve adjacent parts of the same daily-use frustration.

## The problem

Without an allowlist, every navigation, search, file inspection, and read-only git command triggers a "Allow this Bash command?" prompt. Each prompt is a context switch. Across a workday it's hundreds of yeses. None of these commands modify state — approving them mechanically is the worst of both worlds: high friction, no real safety benefit.

`/sandbox` partially solves this on macOS and Linux (and WSL2) by sandboxing the agent at the OS level, but it does not work on native Windows 11. On Windows, the permission allowlist is the primary mechanism.

## How Claude Code permissions work

> **Note on accuracy:** The exact rule syntax has changed over Claude Code's lifetime. Verify against the current docs at `https://docs.claude.com/en/docs/claude-code/iam` and `https://docs.claude.com/en/docs/claude-code/settings` before pasting into production. What follows reflects the stable shape as of 2026-05; field names should match, but spot-check.

### Settings file hierarchy

In order of increasing precedence (later wins):

1. **Global user:** `~/.claude/settings.json`
2. **Project committed:** `<repo>/.claude/settings.json`
3. **Project local (gitignored):** `<repo>/.claude/settings.local.json`

Local always wins, and `settings.local.json` should be in `.gitignore`. ClaudePanes ships a `.gitignore` that excludes `.claude/settings.local.json` already.

### Rule actions

Three actions, all under the `permissions` object:

- `allow` — auto-approve.
- `deny` — auto-reject.
- `ask` — prompt (default behavior for anything not matched).

### Rule pattern syntax

Patterns target a specific tool name followed by a parenthesized matcher:

- `Bash(<command-prefix>:*)` — matches a Bash invocation whose first token (or first two tokens for subcommands like `git status`) matches the prefix. `:*` means "any arguments after".
- `Read(*)` — matches the Read tool on any path. Use globs to scope: `Read(/etc/**)`.
- `Write(*)` / `Edit(*)` — file modification tools. Generally do NOT broadly allow these.

Examples:

- `Bash(ls:*)` — allow `ls` with any args.
- `Bash(git status:*)` — allow `git status` and `git status -sb` etc.
- `Bash(git:*)` — allow ALL git commands (too broad; includes `git push`, `git reset`).

### Reload behavior

Changes to `settings.json` take effect for **new** Claude Code sessions. Existing sessions retain the rules they started with.

## Recommended global allowlist

Paste this `permissions` block into `~/.claude/settings.json`. If you already have a `permissions` block, merge the `allow` array — don't replace it.

```json
{
  "permissions": {
    "allow": [
      "Bash(ls:*)",
      "Bash(dir:*)",
      "Bash(pwd:*)",
      "Bash(cd:*)",
      "Bash(tree:*)",
      "Bash(stat:*)",

      "Bash(cat:*)",
      "Bash(head:*)",
      "Bash(tail:*)",
      "Bash(less:*)",
      "Bash(more:*)",
      "Bash(file:*)",
      "Bash(wc:*)",

      "Bash(grep:*)",
      "Bash(rg:*)",
      "Bash(find:*)",
      "Bash(fd:*)",
      "Bash(where:*)",
      "Bash(which:*)",

      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git show:*)",
      "Bash(git branch:*)",
      "Bash(git remote -v:*)",
      "Bash(git config --get:*)",
      "Bash(git rev-parse:*)",
      "Bash(git ls-files:*)",
      "Bash(git stash list:*)",

      "Bash(ps:*)",
      "Bash(tasklist:*)",
      "Bash(top:*)",
      "Bash(htop:*)",
      "Bash(whoami:*)",
      "Bash(hostname:*)",
      "Bash(uname:*)",
      "Bash(systeminfo:*)",

      "Bash(npm list:*)",
      "Bash(npm view:*)",
      "Bash(pip list:*)",
      "Bash(pip show:*)",
      "Bash(dotnet --info:*)",
      "Bash(dotnet --list-runtimes:*)",
      "Bash(dotnet --list-sdks:*)",
      "Bash(node --version:*)",
      "Bash(python --version:*)",

      "Bash(ping:*)",
      "Bash(nslookup:*)",
      "Bash(dig:*)",
      "Bash(curl --head:*)",
      "Bash(wget --spider:*)",

      "Bash(echo:*)",
      "Bash(date:*)",
      "Bash(env:*)",
      "Bash(printenv:*)",
      "Bash(sleep:*)"
    ]
  }
}
```

## Complete `settings.json` for new users

If `~/.claude/settings.json` does not yet exist, this is a complete, paste-ready file:

```json
{
  "permissions": {
    "allow": [
      "Bash(ls:*)",
      "Bash(pwd:*)",
      "Bash(cat:*)",
      "Bash(head:*)",
      "Bash(tail:*)",
      "Bash(grep:*)",
      "Bash(rg:*)",
      "Bash(find:*)",
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git show:*)",
      "Bash(git branch:*)",
      "Bash(which:*)",
      "Bash(echo:*)"
    ]
  }
}
```

Start small. Add more as you notice patterns. Don't allowlist a command you can't articulate as safe.

## Per-project allowlist

For team repos, commit a project allowlist at `<repo>/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(npm run build:*)",
      "Bash(npm test:*)",
      "Bash(dotnet build:*)",
      "Bash(dotnet test:*)"
    ]
  }
}
```

For per-developer additions, use `<repo>/.claude/settings.local.json`. Ensure `.gitignore` excludes it.

## What NOT to allowlist

Each of these can change state or escalate. Keep them on prompt.

- `Bash(rm:*)` — deletion. `rm -rf .` is one typo away.
- `Bash(git push:*)` — affects remote state.
- `Bash(git reset --hard:*)` — destructive local state change.
- `Bash(git clean:*)` — destructive.
- `Bash(git checkout:*)` — can overwrite uncommitted work.
- `Bash(git rebase:*)` — history rewrite.
- `Bash(curl:*)` without `--head` — can fetch and pipe to shell.
- `Bash(wget:*)` without `--spider` — same.
- `Bash(npm install:*)` / `Bash(pip install:*)` / `Bash(dotnet add:*)` — supply-chain surface.
- `Bash(docker run:*)` — can mount host filesystem.
- `Bash(sudo:*)` — escalation.
- `Bash(chmod:*)` / `Bash(chown:*)` / `Bash(icacls:*)` — permission changes.
- `Bash(mv:*)` / `Bash(cp:*)` — filesystem mutation.
- `Bash(git:*)` (the bare prefix) — too broad; includes every destructive subcommand.
- `Write(*)` / `Edit(*)` — defeats the purpose of having confirmation for changes.

## The `fewer-permission-prompts` skill

Claude Code ships a skill called `fewer-permission-prompts` that scans your transcript history and proposes specific allowlist additions based on the commands you actually run. After a week of normal use, invoke it; the recommendations will be tailored to your real workflow rather than this generic list.

Find it in your skills list or invoke via the Skill tool. Output is a proposed merge into your `settings.json` — review before accepting.

## Interaction with `/sandbox`

- `/sandbox` (macOS, Linux, WSL2) sandboxes the agent at the OS level. Within the sandbox, the agent can run filesystem and network operations without prompting because it physically cannot escape the sandbox.
- The permission allowlist trusts specific commands by pattern match. It is the mechanism on platforms without sandbox support.
- The two are complementary. On Windows native, only the allowlist applies. On WSL2 (recommended for ClaudePanes' WSL panes), both can be used.

## Applying the changes

1. Open `~/.claude/settings.json` (create if missing).
2. If a `permissions.allow` array exists, merge new entries — do not replace.
3. Save the file. Valid JSON only — no trailing commas, no comments.
4. Start a NEW Claude Code session. The rules apply to new sessions; existing sessions keep their original rules.
5. Smoke test: ask Claude to run a known-allowlisted command (e.g. `ls -la`). It should execute without prompting.

## Audit checklist

Before pasting allowlist rules from anywhere (including this doc):

- [ ] Read every rule. Understand what command it allows.
- [ ] Confirm none of the prefixes are destructive subcommands.
- [ ] Check that no rule's prefix is a substring of a destructive command (e.g. `Bash(git:*)` would allow `git push`).
- [ ] Validate the JSON parses (`python -m json.tool ~/.claude/settings.json` or VS Code's built-in JSON validator).
- [ ] Test in a low-stakes project before applying to production work.

## Related

- `security.md` — ClaudePanes' own security posture.
- Claude Code docs: `https://docs.claude.com/en/docs/claude-code/settings`
- Claude Code docs: `https://docs.claude.com/en/docs/claude-code/iam`
