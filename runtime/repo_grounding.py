from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List


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


def _words(alternation: str) -> "re.Pattern[str]":
    # Letters and digits bound a word but "_" does not, so snake_case names such as
    # db_password still match while ordinary words such as "author" or "tokenize" do not.
    return re.compile(rf"(?<![a-z0-9])(?:{alternation})(?![a-z0-9])")


RISK_PATTERNS = [
    ("auth", _words(r"auth|authn|authz|oauth2?|authenticat[a-z]*|authori[sz][a-z]*|login")),
    ("security", _words(r"security|vulnerabilit(?:y|ies)|cve-\d{4}-\d+")),
    ("secret", _words(r"secrets?|private[_ -]?keys?|api[_ -]?keys?|passwords?|passwd")),
    ("token", _words(r"access[_ -]?tokens?|bearer|refresh[_ -]?tokens?|jwt")),
    ("deploy", _words(r"deploy|deploys|deployed|deploying|deployments?")),
    ("publish", _words(r"publish|npm publish|twine upload")),
    ("network", _words(r"requests\.(?:get|post)|urllib|fetch\(|http\.client|socket\.")),
    ("database", _words(r"database|sqlite3?|postgres(?:ql)?|mysql|migrations?")),
    ("shell", _words(r"subprocess|os\.system|shell=true|exec\(|eval\(")),
    ("permission", _words(r"chmod|chown|sudo|setuid|permissions?")),
]

TEXT_SUFFIXES = {
    "", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb",
    ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".swift", ".gd", ".sh", ".bash", ".yml", ".yaml",
    ".toml", ".json", ".ini", ".cfg", ".env", ".sql", ".tf", ".md", ".txt", ".rst",
}


class RepoGroundingEngine:
    """Collects grounded repo facts from files and manifests."""

    EXCLUDED_DIRS = {
        ".git", "node_modules", "dist", "build", "venv", ".venv", "target", "__pycache__",
        ".mypy_cache", ".pytest_cache", ".tox", "site-packages",
    }

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

        evidence: List[str] = list(key_files)
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
                except (OSError, UnicodeError):
                    return ""
        return ""

    def _detect_manifests(self) -> List[str]:
        manifests = {
            "package.json", "pyproject.toml", "setup.py", "requirements.txt", "Cargo.toml",
            "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
            "Gemfile", "mix.exs", "project.godot",
        }
        found: List[str] = []
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [directory for directory in dirs if directory not in self.EXCLUDED_DIRS]
            for filename in files:
                if filename in manifests:
                    found.append(os.path.relpath(os.path.join(root, filename), self.repo_root))
        return sorted(found)

    def _detect_project_type(self, manifests: List[str]) -> str:
        if not manifests:
            return "UNKNOWN"
        root_manifests = [
            path for path in manifests
            if os.path.dirname(path) in {"", "."}
        ]
        candidates = root_manifests or manifests
        lowered = [path.lower() for path in candidates]
        if any(path.endswith("package.json") for path in lowered):
            return "node"
        if any(path.endswith(("pyproject.toml", "requirements.txt", "setup.py")) for path in lowered):
            return "python"
        if any(path.endswith("cargo.toml") for path in lowered):
            return "rust"
        if any(path.endswith("go.mod") for path in lowered):
            return "go"
        if any(path.endswith(("pom.xml", "build.gradle", "build.gradle.kts")) for path in lowered):
            return "java"
        if any(path.endswith("composer.json") for path in lowered):
            return "php"
        if any(path.endswith("gemfile") for path in lowered):
            return "ruby"
        if any(path.endswith("project.godot") for path in lowered):
            return "godot"
        return "UNKNOWN"

    def _pick_key_files(self, manifests: List[str]) -> List[str]:
        observed = list(manifests)
        wanted = {
            "README.md", "CLAUDE.md", "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
            "pom.xml", "requirements.txt", "project.godot",
        }
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [directory for directory in dirs if directory not in self.EXCLUDED_DIRS]
            for name in files:
                if name in wanted:
                    relative = os.path.relpath(os.path.join(root, name), self.repo_root)
                    if relative not in observed:
                        observed.append(relative)
        return observed[:15]

    def _pick_key_directories(self) -> List[str]:
        directories: List[str] = []
        for root, dirs, _ in os.walk(self.repo_root):
            dirs[:] = [directory for directory in dirs if directory not in self.EXCLUDED_DIRS]
            relative = os.path.relpath(root, self.repo_root)
            if relative != "." and relative.count(os.sep) <= 2:
                directories.append(relative)
        return directories[:15]

    def _infer_purpose(self, readme_text: str) -> str:
        if not readme_text:
            return "UNKNOWN"
        lines = [line.strip() for line in readme_text.splitlines() if line.strip()]
        for line in lines[:12]:
            if len(line) > 20 and not line.startswith("#"):
                return line[:180]
        return "Repository purpose is not explicitly described in README."

    def _godot_script_runners(self, project_root: str) -> List[str]:
        """Repository-relative scripts that run headless because they extend SceneTree."""
        runners: List[str] = []
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS and d not in {"addons", ".godot"}]
            for filename in sorted(files):
                if not filename.endswith(".gd"):
                    continue
                path = os.path.join(root, filename)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        head = [line.strip() for line in handle.readlines()[:20]]
                except OSError:
                    continue
                code = [line for line in head if line and not line.startswith("#")]
                if code and code[0] == "extends SceneTree":
                    runners.append(os.path.relpath(path, project_root).replace(os.sep, "/"))
        return sorted(runners)

    def _has_tests(self, project_root: str) -> bool:
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [directory for directory in dirs if directory not in self.EXCLUDED_DIRS]
            if any(filename.startswith("test_") and filename.endswith(".py") for filename in files):
                return True
        return False

    def _discover_commands(self, manifests: List[str]) -> List[str]:
        """Suggest commands only when the repository contains evidence that supports them."""
        commands: List[str] = []
        root_tests = self._has_tests(self.repo_root)
        if root_tests:
            commands.append("python -m unittest discover -s tests -v")

        for manifest in manifests:
            full_path = os.path.join(self.repo_root, manifest)
            manifest_dir = os.path.dirname(full_path) or self.repo_root
            lower = manifest.lower()

            if lower.endswith("package.json"):
                try:
                    with open(full_path, "r", encoding="utf-8") as handle:
                        package = json.load(handle)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    package = {}
                scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
                if isinstance(scripts, dict):
                    for script_name in sorted(scripts):
                        if not isinstance(script_name, str) or not script_name.strip():
                            continue
                        commands.append("npm test" if script_name == "test" else f"npm run {script_name}")
                if os.path.isfile(os.path.join(manifest_dir, "package-lock.json")):
                    commands.append("npm ci")
                else:
                    commands.append("npm install")

            if lower.endswith("requirements.txt"):
                commands.append(f"python -m pip install -r {manifest}")

            if lower.endswith(("pyproject.toml", "requirements.txt", "setup.py")):
                config_paths = [
                    os.path.join(manifest_dir, "pytest.ini"),
                    os.path.join(manifest_dir, "tox.ini"),
                    os.path.join(manifest_dir, "setup.cfg"),
                    os.path.join(manifest_dir, "pyproject.toml"),
                ]
                pytest_configured = False
                for config_path in config_paths:
                    if not os.path.isfile(config_path):
                        continue
                    try:
                        with open(config_path, "r", encoding="utf-8", errors="replace") as handle:
                            content = handle.read().lower()
                        if "[tool.pytest" in content or "[pytest]" in content or "pytest" in content:
                            pytest_configured = True
                            break
                    except OSError:
                        continue
                if self._has_tests(manifest_dir) or pytest_configured:
                    commands.append("python -m pytest")

            if lower.endswith("cargo.toml"):
                commands.extend(["cargo test", "cargo build"])
            if lower.endswith("go.mod"):
                commands.extend(["go test ./...", "go build ./..."])
            if lower.endswith("pom.xml"):
                commands.append("mvn test")
            if lower.endswith(("build.gradle", "build.gradle.kts")):
                wrapper = os.path.join(manifest_dir, "gradlew")
                commands.append("./gradlew test" if os.path.isfile(wrapper) else "gradle test")
            if lower.endswith("composer.json"):
                commands.append("composer install")
            if lower.endswith("project.godot"):
                # The engine binary name varies per install; "godot" stands for it.
                project = os.path.relpath(manifest_dir, self.repo_root).replace(os.sep, "/")
                commands.append(f"godot --headless --path {project} --import")
                for runner in self._godot_script_runners(manifest_dir):
                    commands.append(f"godot --headless --path {project} --script res://{runner}")

        return list(dict.fromkeys(commands))

    def _detect_risks(self) -> List[str]:
        findings: List[str] = []
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [directory for directory in dirs if directory not in self.EXCLUDED_DIRS]
            for filename in sorted(files):
                full_path = os.path.join(root, filename)
                lowered_name = filename.lower()
                env_file = lowered_name in {".env", "env.example"} or lowered_name.startswith(".env.")
                if env_file or lowered_name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
                    findings.append("Configuration and environment exposure risk")
                if not env_file and os.path.splitext(lowered_name)[1] not in TEXT_SUFFIXES:
                    continue
                try:
                    if os.path.getsize(full_path) > 1_000_000:
                        continue
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as handle:
                        content = handle.read().lower()
                except OSError:
                    continue
                for term, pattern in RISK_PATTERNS:
                    if pattern.search(content):
                        findings.append(f"Potential risk area: {term}")
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
