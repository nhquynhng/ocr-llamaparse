from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

try:
    from src.validation.apply_metadata import FIELD_ORDER, iter_markdown_files, is_empty, split_front_matter
except ModuleNotFoundError:  # Allow direct execution from src/validation.
    from apply_metadata import FIELD_ORDER, iter_markdown_files, is_empty, split_front_matter


try:
    from src.validation.apply_metadata import (
        BACKEND_DOCUMENT_TYPES,
        BACKEND_FILE_TYPES,
        BACKEND_OCR_STATUSES,
        BACKEND_RAG_STATUSES,
        BACKEND_REVIEW_STATUSES,
    )
except ModuleNotFoundError:  # Allow direct execution from src/validation.
    from apply_metadata import (
        BACKEND_DOCUMENT_TYPES,
        BACKEND_FILE_TYPES,
        BACKEND_OCR_STATUSES,
        BACKEND_RAG_STATUSES,
        BACKEND_REVIEW_STATUSES,
    )

ENUMS = {
    "ocr_status": BACKEND_OCR_STATUSES,
    "review_status": BACKEND_REVIEW_STATUSES,
    "rag_status": BACKEND_RAG_STATUSES,
    "document_type": BACKEND_DOCUMENT_TYPES,
    "file_type": BACKEND_FILE_TYPES,
}

CORE_METADATA_FIELDS = [
    "document_key",
    "version_key",
    "title",
    "document_type",
    "domain",
    "responsible_department",
    "audience",
    "is_latest",
    "source_path",
    "canonical_markdown_path",
    "file_type",
    "language",
    "checksum",
    "ocr_status",
    "review_status",
    "rag_status",
]

AUTO_REQUIRED_FIELDS = {
    "document_key",
    "version_key",
    "document_type",
    "is_latest",
    "ocr_status",
    "review_status",
    "rag_status",
    "canonical_markdown_path",
    "file_type",
    "language",
    "checksum",
}

HUMAN_REVIEW_FIELDS = {
    "title",
    "domain",
    "responsible_department",
    "audience",
}

OPTIONAL_HUMAN_FIELDS = {
    "code",
    "issued_date",
    "effective_date",
    "status_note",
    "source_url",
    "source_path",
    "accessed_date",
    "related_asset_keys",
    "parser",
    "ocr_engine",
    "notes",
}

DATE_FIELDS = {"issued_date", "effective_date", "accessed_date"}
LIST_FIELDS = {"related_asset_keys"}


def scalar(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def validate_metadata_text(text: str) -> tuple[list[str], list[str]]:
    metadata, _body = split_front_matter(text)
    errors: list[str] = []
    warnings: list[str] = []

    if not metadata:
        return ["missing YAML front matter"], []

    for field in CORE_METADATA_FIELDS:
        if field not in metadata:
            errors.append(f"missing field: {field}")

    for field in metadata:
        if field not in FIELD_ORDER:
            warnings.append(f"unknown field: {field}")

    for field in AUTO_REQUIRED_FIELDS:
        if field in metadata and is_empty(metadata.get(field)):
            errors.append(f"auto required field is empty: {field}")

    for field in HUMAN_REVIEW_FIELDS:
        if field in metadata and is_empty(metadata.get(field)):
            warnings.append(f"needs human review: {field} is empty")

    for field in OPTIONAL_HUMAN_FIELDS:
        if field in metadata and is_empty(metadata.get(field)):
            warnings.append(f"optional human field is empty: {field}")

    if "audience" in metadata and not is_empty(metadata.get("audience")):
        if not isinstance(metadata.get("audience"), list):
            errors.append("audience must be a list")
        elif any(not isinstance(item, str) or not item for item in metadata["audience"]):
            errors.append("audience must contain non-empty strings")

    for field in LIST_FIELDS:
        if field in metadata and not is_empty(metadata.get(field)):
            if not isinstance(metadata.get(field), list):
                errors.append(f"{field} must be a list")
            elif any(not isinstance(item, str) or not item for item in metadata[field]):
                errors.append(f"{field} must contain non-empty strings")

    if "is_latest" in metadata and not isinstance(metadata.get("is_latest"), bool):
        errors.append("is_latest must be true or false")

    for field, allowed in ENUMS.items():
        if field not in metadata or is_empty(metadata.get(field)):
            continue
        value = metadata.get(field)
        if not isinstance(value, str):
            errors.append(f"{field} must be a string enum")
        elif value not in allowed:
            errors.append(f"{field} has invalid enum: {value}")

    if scalar(metadata, "document_type") == "unknown":
        warnings.append("needs human review: document_type is unknown")

    checksum = scalar(metadata, "checksum")
    if checksum and not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        errors.append("checksum must be a 64-character SHA256 hex string")

    for field in DATE_FIELDS:
        value = scalar(metadata, field)
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            errors.append(f"{field} must use YYYY-MM-DD")

    if scalar(metadata, "rag_status") == "published":
        if scalar(metadata, "ocr_status") != "done":
            errors.append("published document must have ocr_status done")
        if scalar(metadata, "review_status") != "approved":
            errors.append("published document must have review_status approved")

    return errors, warnings


def validate_one(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    return validate_metadata_text(text)


def print_result(path: Path, errors: list[str], warnings: list[str]) -> None:
    if errors:
        status = "ERROR"
    elif warnings:
        status = "WARN"
    else:
        status = "OK"

    print(f"[{status}] {path}")
    for item in errors:
        print(f"  error: {item}")
    for item in warnings:
        print(f"  warn: {item}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate canonical YAML metadata in Markdown files.")
    parser.add_argument("path", help="Markdown file or directory.")
    parser.add_argument("--recursive", "-r", action="store_true", help="Validate *.md recursively when path is a directory.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    target = Path(args.path)
    files = iter_markdown_files(target, args.recursive)
    if not files:
        print(f"[WARN] No Markdown files found: {target}")
        return 1

    total_errors = 0
    total_warnings = 0
    for path in files:
        errors, warnings = validate_one(path)
        print_result(path, errors, warnings)
        total_errors += len(errors)
        total_warnings += len(warnings)

    print(f"[DONE] files={len(files)} errors={total_errors} warnings={total_warnings}")
    if total_errors:
        return 1
    if args.strict and total_warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
