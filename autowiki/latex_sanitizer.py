import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_BARE_LATEX_RE = re.compile(r"^\\{1,2}([a-zA-Z{_])")


def _frontmatter_end(lines: list[str]) -> int:
    """Return the index of the closing --- of YAML frontmatter, or -1."""
    if not lines or lines[0].strip() != "---":
        return -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return -1


def sanitize_file(path: Path) -> int:
    lines = path.read_text().splitlines(True)
    changed = 0
    in_code = False
    fm_end = _frontmatter_end(lines)

    for i in range(len(lines)):
        if i <= fm_end:
            continue

        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("#"):
            continue

        new_line = line
        new_line = new_line.replace("\\(", "$")
        new_line = new_line.replace("\\)", "$")
        new_line = new_line.replace("\\[", "$$")
        new_line = new_line.replace("\\]", "$$")

        if new_line != line:
            lines[i] = new_line
            changed += 1
            continue

        if not _BARE_LATEX_RE.match(stripped):
            continue

        prefix = line[: len(line) - len(line.lstrip())]
        if stripped.endswith("\\"):
            stripped = stripped.rstrip("\\")
        stripped = stripped.replace("\\\\", "\\")
        lines[i] = f"{prefix}$$ {stripped} $$\n"
        changed += 1

    if changed:
        path.write_text("".join(lines))
        log.info("Sanitized %d bare-LaTeX lines in %s", changed, path.name)
    return changed


def sanitize_dir(wiki_dir: Path) -> int:
    total = 0
    for md in sorted(wiki_dir.glob("*.md")):
        if md.name.startswith("."):
            continue
        try:
            total += sanitize_file(md)
        except Exception:
            log.exception("Failed to sanitize %s", md.name)
    return total
