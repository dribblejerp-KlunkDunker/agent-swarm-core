from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class RepoFact:
    repo_name: str
    purpose: str
    project_type: str
    key_directories: List[str]
    key_files: List[str]
    commands: List[str]
    risks: List[str]
    unknowns: List[str]
    evidence: List[str] = field(default_factory=list)


class RepoGroundingEngine:
    """Collects grounded repo facts from files and manifests."""

    def __init__(self, repo_root: str):
        self.repo_root = repo_root

    def inspect(self) -> RepoFact:
        repo_name = os.path.basename(os.path.abspath(self.repo_root))
        readme_text = self._read_first_matching_file(["README.md", "README.MD", "README.rst", "README.txt"])
        purpose = self._infer_purpose(readme_text)

        manifests = self._detect_manifests()
        project_type = self._detect_project_type(manifests)
        key_files = self._pick_key_files(manifests)
        commands = self._discover_commands(manifests)
        key_dirs = self._pick_key_directories()
        risks = self._detect_risks()
        unknowns = self._detect_unknowns(manifests, readme_text)

        evidence: List[str] = []
        for path in key_files:
            evidence.append(f"{path}")
        if readme_text:
            evidence.append("README")

        return RepoFact(
            repo_name=repo_name,
            purpose=purpose,
            project_type=project_type,
            key_directories=key_dirs,
            key_files=key_files,
            commands=commands,
            risks=risks,
            unknowns=unknowns,
            evidence=evidence,
        )

    def _read_first_matching_file(self, names: List[str]) -> str:
        for name in names:
            candidate = os.path.join(self.repo_root, name)
            if os.path.exists(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as handle:
                        return handle.read()
                except Exception:
                    return ""
        return ""

    def _detect_manifests(self) -> List[str]:
        manifests = [
            "package.json",
            "pyproject.toml",
            "setup.py",
            "requirements.txt",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "composer.json",
            "Gemfile",
            "mix.exs",
        ]
        found: List[str] = []
        for root, _, files in os.walk(self.repo_root):
            for fname in files:
                if fname in manifests:
                    found.append(os.path.relpath(os.path.join(root, fname), self.repo_root))
        return found

    def _detect_project_type(self, manifests: List[str]) -> str:
        if not manifests:
            return "UNKNOWN"
        lowered = [m.lower() for m in manifests]
        if any("package.json" in item for item in lowered):
            return "node"
        if any("pyproject.toml" in item or "requirements.txt" in item or "setup.py" in item for item in lowered):
            return "python"
        if any("cargo.toml" in item for item in lowered):
            return "rust"
        if any("go.mod" in item for item in lowered):
            return "go"
        if any("pom.xml" in item or "build.gradle" in item for item in lowered):
            return "java"
        if any("composer.json" in item for item in lowered):
            return "php"
        if any("gemfile" in item for item in lowered):
            return "ruby"
        return "UNKNOWN"

    def _pick_key_files(self, manifests: List[str]) -> List[str]:
        candidates = [
            "README.md",
            "README.rst",
            "README.txt",
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "requirements.txt",
            ".github/workflows",
            ".agent",
        ]
        observed: List[str] = []
        for path in manifests:
            observed.append(path)
        for root, _, files in os.walk(self.repo_root):
            for name in files:
                if name in {"README.md", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "requirements.txt"}:
                    rel = os.path.relpath(os.path.join(root, name), self.repo_root)
                    if rel not in observed:
                        observed.append(rel)
        return observed[:15]

    def _pick_key_directories(self) -> List[str]:
        forbidden = {".git", "node_modules", "dist", "build", "venv", ".venv", "target", "__pycache__"}
        directories: List[str] = []
        for root, dirs, _ in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in forbidden]
            rel = os.path.relpath(root, self.repo_root)
            if rel == ".":
                continue
            if rel.count(os.sep) <= 2:
                directories.append(rel)
        return directories[:15]

    def _infer_purpose(self, readme_text: str) -> str:
        if not readme_text:
            return "UNKNOWN"
        lines = [line.strip() for line in readme_text.splitlines() if line.strip()]
        for line in lines[:12]:
            if len(line) > 20 and not line.startswith("#"):
                return line[:180]
        return "Repository purpose is not explicitly described in README."

    def _discover_commands(self, manifests: List[str]) -> List[str]:
        commands: List[str] = []
        for manifest in manifests:
            lower = manifest.lower()
            if "package.json" in lower:
                commands.extend([
                    "npm test",
                    "npm run build",
                    "npm install",
                ])
            if "pyproject.toml" in lower or "requirements.txt" in lower:
                commands.extend([
                    "python -m pytest",
                    "python -m pip install -r requirements.txt",
                ])
            if "cargo.toml" in lower:
                commands.extend([
                    "cargo test",
                    "cargo build",
                ])
            if "go.mod" in lower:
                commands.extend([
                    "go test ./...",
                    "go build ./...",
                ])
            if "pom.xml" in lower or "build.gradle" in lower:
                commands.extend([
                    "mvn test",
                    "gradle test",
                ])
        return list(dict.fromkeys(commands))

    def _detect_risks(self) -> List[str]:
        risk_terms = [
            "auth",
            "security",
            "secret",
            "token",
            "deploy",
            "publish",
            "network",
            "database",
            "shell",
            "permission",
        ]
        findings: List[str] = []
        for root, _, files in os.walk(self.repo_root):
            for name in files:
                full = os.path.join(root, name)
                lower_name = name.lower()
                if lower_name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "env.example", ".env"}:
                    findings.append("Configuration and environment exposure risk")
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as handle:
                        text = handle.read().lower()
                except Exception:
                    continue
                for term in risk_terms:
                    if term in text:
                        findings.append(f"Potential risk area: {term}")
                        break
        return list(dict.fromkeys(findings))[:10]

    def _detect_unknowns(self, manifests: List[str], readme_text: str) -> List[str]:
        unknowns: List[str] = []
        if not readme_text:
            unknowns.append("README not found; repository purpose is unknown")
        if not manifests:
            unknowns.append("No supported manifest detected; project type is unknown")
        return unknowns

    def to_dict(self) -> Dict[str, object]:
        facts = self.inspect()
        return {
            "repo_name": facts.repo_name,
            "purpose": facts.purpose,
            "project_type": facts.project_type,
            "key_directories": facts.key_directories,
            "key_files": facts.key_files,
            "commands": facts.commands,
            "risks": facts.risks,
            "unknowns": facts.unknowns,
            "evidence": facts.evidence,
        }


def main() -> None:
    repo_root = os.getcwd()
    engine = RepoGroundingEngine(repo_root)
    result = engine.to_dict()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
