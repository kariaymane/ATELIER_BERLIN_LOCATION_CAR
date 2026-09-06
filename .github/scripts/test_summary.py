"""Emit bounded, redacted test/build diagnostics as GitHub Actions annotations."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def redact(text: str) -> str:
    """Keep error structure while suppressing literal values and request details."""
    workspace = os.environ.get("GITHUB_WORKSPACE", "")
    if workspace:
        text = text.replace(workspace + "/", "")
    text = re.sub(r"(?:https?|postgres(?:ql)?(?:\+\w+)?)://\S+", "[URL omitted]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email omitted]", text)
    text = re.sub(r"([\"'])(?:\\.|(?!\1).)*?\1", "[literal omitted]", text)
    text = re.sub(r"\b[A-Za-z0-9_+/=-]{24,}\b", "[value omitted]", text)
    text = re.sub(r"(?i)((?:password|secret|token|api_key)\s*[:=])[^\s,;]+", r"\1[omitted]", text)
    return text[:1500]


def annotate(message: str) -> None:
    escaped = redact(message).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error::{escaped}")


def report_xml(paths: list[Path]) -> int:
    failures = 0
    for path in paths:
        if not path.is_file():
            continue
        for case in ET.parse(path).getroot().iter("testcase"):
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            if problem is None:
                continue
            if failures < 20:
                identifier = f"{case.get('classname', '')}.{case.get('name', '')}"
                message = problem.get("message", "") or (problem.text or "").split("\n")[0]
                annotate(identifier + ": " + message)
            failures += 1
    print(f"Test failures reported: {failures}")
    return failures


def report_build(path: Path) -> None:
    if not path.is_file():
        return
    lines = path.read_text(errors="replace").splitlines()
    selected = []
    for index, line in enumerate(lines):
        if line.startswith(("e: ", "Execution failed for task", "> ")):
            selected.append(line)
        elif line.startswith("* What went wrong:"):
            selected.extend(lines[index + 1:index + 5])
    for line in selected[-20:]:
        annotate(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", nargs="*", type=Path)
    parser.add_argument("--build-log", type=Path)
    args = parser.parse_args()
    report_xml(args.xml)
    if args.build_log:
        report_build(args.build_log)


if __name__ == "__main__":
    main()
