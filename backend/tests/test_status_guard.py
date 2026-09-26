"""transition() must be the only code that changes a post's status."""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
STATE_MACHINE_MODULE = APP_DIR / "post_status.py"
STATUS_ASSIGNMENT = re.compile(r"\.status\s*=(?!=)")


def test_guard_pattern_catches_assignments_but_not_comparisons():
    assert STATUS_ASSIGNMENT.search("post.status = PostStatus.APPROVED")
    assert STATUS_ASSIGNMENT.search("post.status=new_status")
    assert not STATUS_ASSIGNMENT.search("if post.status == PostStatus.DRAFT:")


def test_only_the_state_machine_assigns_post_status():
    offending_lines = []
    for source_path in sorted(APP_DIR.rglob("*.py")):
        if source_path == STATE_MACHINE_MODULE:
            continue
        for line_number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), start=1):
            if STATUS_ASSIGNMENT.search(line):
                offending_lines.append(f"{source_path.relative_to(APP_DIR.parent)}:{line_number}: {line.strip()}")

    assert not offending_lines, "Change post status only via transition() in app/post_status.py:\n" + "\n".join(
        offending_lines
    )
