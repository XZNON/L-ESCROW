#!/usr/bin/env python3
"""
doc-audit.py — Drift detection + auto-update for CLAUDE.md files.
Called by doc-sync.sh with the path of the just-edited source file.
Uses 'claude -p' to surgically update stale doc sections, then auto-commits.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_nearest_claude_md(source_path: Path) -> Path | None:
    """Walk up from source_path until we find a CLAUDE.md."""
    current = source_path.parent
    repo_root = Path(subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel'], text=True
    ).strip())
    while current >= repo_root:
        candidate = current / 'CLAUDE.md'
        if candidate.exists():
            return candidate
        if current == repo_root:
            break
        current = current.parent
    return None


def extract_python_surface(source: str) -> list[str]:
    """Extract public function/class names and their docstrings from Python source."""
    surface = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith('_'):
                    continue
                doc = ast.get_docstring(node) or ""
                args = ""
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arg_names = [a.arg for a in node.args.args if a.arg != 'self']
                    args = f"({', '.join(arg_names)})"
                surface.append(f"{node.name}{args}: {doc[:80]}")
    except SyntaxError:
        pass
    return surface


def extract_surface(source_path: Path) -> list[str]:
    content = source_path.read_text(errors='replace')
    if source_path.suffix == '.py':
        return extract_python_surface(content)
    # Fallback: grep for exported/public names
    names = re.findall(r'^(?:export\s+)?(?:function|class|def|const|let|var)\s+(\w+)', content, re.M)
    return [n for n in names if not n.startswith('_')]


def is_stale(doc_content: str, surface: list[str]) -> bool:
    """Quick heuristic: any surface name missing from the doc?"""
    if not surface:
        return False
    mentioned = 0
    for item in surface:
        name = item.split('(')[0].split(':')[0].strip()
        if name and name in doc_content:
            mentioned += 1
    # If less than half of public symbols are mentioned, flag as potentially stale
    return mentioned < len(surface) * 0.5


def call_claude(prompt: str) -> str:
    """Call claude CLI with a prompt. Returns stdout."""
    result = subprocess.run(
        ['claude', '-p', prompt],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout.strip()


def git_commit(files: list[str], message: str) -> None:
    subprocess.run(['git', 'add'] + files, check=False)
    subprocess.run(['git', 'commit', '-m', message], check=False)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: doc-audit.py <changed_file_path>")
        sys.exit(1)

    source_path = Path(sys.argv[1])
    if not source_path.exists():
        print(f"File not found: {source_path}")
        sys.exit(0)

    claude_md = find_nearest_claude_md(source_path)
    if not claude_md:
        print(f"No CLAUDE.md found for {source_path}")
        sys.exit(0)

    print(f"Auditing {source_path} against {claude_md}")

    surface = extract_surface(source_path)
    if not surface:
        print("No public surface extracted — skipping")
        sys.exit(0)

    doc_content = claude_md.read_text()
    if not is_stale(doc_content, surface):
        print("Doc looks up-to-date — no update needed")
        sys.exit(0)

    print(f"Drift detected — calling Claude to update {claude_md.name}")

    source_content = source_path.read_text(errors='replace')
    surface_summary = '\n'.join(f"  - {s}" for s in surface[:20])

    prompt = f"""You are a documentation maintainer. A source file was edited and some docs may be stale.

SOURCE FILE: {source_path.name}
```
{source_content[:3000]}
```

CURRENT CLAUDE.md (the doc to update):
```
{doc_content[:3000]}
```

PUBLIC SURFACE OF SOURCE FILE:
{surface_summary}

TASK: Update ONLY the stale parts of the CLAUDE.md. Preserve all existing sections.
Add any new public functions/classes not yet mentioned. Remove references to deleted items.
Do NOT rewrite sections that are still accurate. Output the complete updated CLAUDE.md, nothing else.
"""

    updated = call_claude(prompt)
    if not updated or len(updated) < 50:
        print("Claude returned empty/short response — skipping update")
        sys.exit(0)

    claude_md.write_text(updated)
    print(f"Updated {claude_md}")

    git_commit(
        [str(claude_md)],
        f"docs: auto-sync {source_path.name} → {claude_md.name}"
    )
    print("Committed doc update")


if __name__ == '__main__':
    main()
