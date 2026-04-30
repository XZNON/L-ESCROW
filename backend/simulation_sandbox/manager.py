import difflib
import json
import shutil
from pathlib import Path

SANDBOX_PATH = Path(__file__).parent


class SimulationManager:
    def __init__(self, base: Path = SANDBOX_PATH):
        self.base = base
        self.repo = base / "repo"
        self.prs = base / "prs"
        self.template = base / "_template" / "repo"
        self.issues_path = base / "issues.json"

    def reset_sandbox(self) -> None:
        for src in self.template.glob("*.py"):
            shutil.copy2(src, self.repo / src.name)
        for pr in self.prs.glob("*.py"):
            pr.unlink()

    def get_issues(self) -> list:
        return json.loads(self.issues_path.read_text(encoding="utf-8"))

    def merge_fix(self, rfp_id: str, sandbox_file: str) -> bool:
        matches = list(self.prs.glob(f"pr_*_{rfp_id}.py"))
        if not matches:
            return False
        shutil.copy2(matches[0], self.repo / sandbox_file)
        return True

    def get_diff(self, sandbox_file: str, rfp_id: str) -> str:
        repo_file = self.repo / sandbox_file
        if not repo_file.exists():
            return ""
        original = repo_file.read_text(encoding="utf-8")
        pr_matches = list(self.prs.glob(f"pr_*_{rfp_id}.py"))
        if not pr_matches:
            return ""
        proposed = pr_matches[0].read_text(encoding="utf-8")
        return "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"repo/{sandbox_file}",
            tofile=f"prs/{pr_matches[0].name}",
        ))

    def read_repo_file(self, sandbox_file: str) -> str:
        path = self.repo / sandbox_file
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def find_pr_file(self, rfp_id: str) -> Path | None:
        matches = list(self.prs.glob(f"pr_*_{rfp_id}.py"))
        return matches[0] if matches else None


sim_manager = SimulationManager()
