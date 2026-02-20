"""
Release Notes Generator
========================

Generates release notes for an incremental deployment package.
The notes summarise what was changed, added, or deleted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from attrs import define, field

from dblocks_core.config.config import logger
from dblocks_core.git import git


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@define
class ReleaseNoteEntry:
    """Single entry in the release notes."""

    action: str  # ADDED | MODIFIED | DELETED | RENAMED
    object_type: str  # TABLE | VIEW | PROCEDURE | …
    database_name: str
    object_name: str
    details: str = field(default="")


@define
class ReleaseNotes:
    """Complete release notes for a package."""

    package_name: str
    generated_at: datetime
    entries: list[ReleaseNoteEntry] = field(factory=list)
    warnings: list[str] = field(factory=list)


# ---------------------------------------------------------------------------
# Extension to object type mapping (mirrors fsystem.EXT_TO_TYPE)
# ---------------------------------------------------------------------------

_EXT_TO_OBJECT_TYPE: dict[str, str] = {
    ".tab": "TABLE",
    ".viw": "VIEW",
    ".pro": "PROCEDURE",
    ".mcr": "MACRO",
    ".fnc": "FUNCTION",
    ".mfnc": "FUNCTION MAPPING",
    ".trg": "TRIGGER",
    ".jix": "JOIN INDEX",
    ".idx": "INDEX",
    ".type": "TYPE",
    ".auth": "AUTHORIZATION",
    ".sql": "SQL",
    ".bteq": "BTEQ",
    ".dtb": "DATABASE",
    ".usr": "USER",
    ".rol": "ROLE",
    ".prf": "PROFILE",
}


def _object_type_from_path(path: Path) -> str:
    """Derive the object type from a file's extension."""
    return _EXT_TO_OBJECT_TYPE.get(path.suffix.lower(), "UNKNOWN")


def _database_from_path(path: Path) -> str:
    """Derive the database name from the file's parent directory."""
    return path.parent.name


# ---------------------------------------------------------------------------
# Build release notes
# ---------------------------------------------------------------------------


def build_release_notes(
    changes: list[git.GitChangedPath],
    package_name: str,
    *,
    warnings: list[str] | None = None,
    ts: datetime | None = None,
) -> ReleaseNotes:
    """Build release notes from the list of git changes.

    Args:
        changes: List of changed files from git diff.
        package_name: Name of the package being created.
        warnings: Optional list of warnings from the change script
            generation process.
        ts: Optional fixed timestamp.

    Returns:
        A ``ReleaseNotes`` instance.
    """

    ts = ts or datetime.now()
    notes = ReleaseNotes(
        package_name=package_name,
        generated_at=ts,
        warnings=list(warnings or []),
    )

    for change in changes:
        action = _action_label(change.change)
        obj_type = _object_type_from_path(change.rel_path)
        db_name = _database_from_path(change.rel_path)
        obj_name = change.rel_path.stem

        detail = ""
        if change.change == git.FileStatus.RENAMED:
            if change.rename_from_rel_path:
                detail = f"renamed from {change.rename_from_rel_path}"

        notes.entries.append(
            ReleaseNoteEntry(
                action=action,
                object_type=obj_type,
                database_name=db_name,
                object_name=obj_name,
                details=detail,
            )
        )

    return notes


def _action_label(status: git.FileStatus) -> str:
    """Map a git file status to a human-readable action."""
    _map = {
        git.FileStatus.ADDED: "ADDED",
        git.FileStatus.MODIFIED: "MODIFIED",
        git.FileStatus.DELETED: "DELETED",
        git.FileStatus.RENAMED: "RENAMED",
        git.FileStatus.COPIED: "COPIED",
        git.FileStatus.UNTRACKED: "ADDED",
        git.FileStatus.UNMERGED: "MODIFIED",
    }
    return _map.get(status, "UNKNOWN")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_release_notes(notes: ReleaseNotes) -> str:
    """Render release notes to a Markdown string."""

    lines: list[str] = []
    lines.append(f"# Release Notes: {notes.package_name}")
    lines.append("")
    lines.append(f"**Generated:** {notes.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # warnings
    if notes.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in notes.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    # group by action
    by_action: dict[str, list[ReleaseNoteEntry]] = {}
    for entry in notes.entries:
        by_action.setdefault(entry.action, []).append(entry)

    # order: ADDED, MODIFIED, DELETED, RENAMED, rest
    action_order = ["ADDED", "MODIFIED", "DELETED", "RENAMED", "COPIED"]
    ordered_actions = [a for a in action_order if a in by_action]
    ordered_actions.extend(a for a in sorted(by_action) if a not in action_order)

    for action in ordered_actions:
        entries = by_action[action]
        lines.append(f"## {action} ({len(entries)})")
        lines.append("")
        lines.append("| Object Type | Database | Object Name | Details |")
        lines.append("|-------------|----------|-------------|---------|")
        for e in entries:
            lines.append(
                f"| {e.object_type} | {e.database_name} | {e.object_name} | {e.details} |"
            )
        lines.append("")

    # summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total changes: {len(notes.entries)}")
    for action in ordered_actions:
        lines.append(f"- {action}: {len(by_action[action])}")
    lines.append("")

    return "\n".join(lines)
