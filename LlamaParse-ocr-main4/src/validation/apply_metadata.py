from __future__ import annotations

import argparse
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SRC_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
NLCS_ROOT = PROJECT_ROOT / "nlcs" if (PROJECT_ROOT / "nlcs").exists() else PROJECT_ROOT

FIELD_ORDER = [
    "document_key",
    "version_key",
    "title",
    "document_type",
    "domain",
    "department",
    "audience",
    "code",
    "issued_date",
    "effective_date",
    "expiry_date",
    "version_label",
    "is_latest",
    "validity_status",
    "version_role",
    "replaces",
    "replaced_by",
    "amends",
    "amended_by",
    "supplements",
    "supplemented_by",
    "collection_status",
    "ocr_status",
    "review_status",
    "rag_status",
    "status_note",
    "source_url",
    "source_file",
    "source_path",
    "canonical_markdown_path",
    "file_type",
    "accessed_date",
    "language",
    "citation_type",
    "related_asset_keys",
    "checksum",
    "parser",
    "ocr_engine",
    "created_at",
    "updated_at",
    "notes",
]

HUMAN_STRING_FIELDS = {
    "title",
    "domain",
    "department",
    "code",
    "version_label",
    "status_note",
    "source_url",
    "notes",
}

HUMAN_NULL_FIELDS = {
    "issued_date",
    "effective_date",
    "expiry_date",
    "accessed_date",
}

SOURCE_EXTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".xlsx",
    ".csv",
    ".html",
    ".txt",
}

FILE_TYPE_BY_EXT = {
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
    ".pptx": "pptx",
    ".md": "md",
    ".html": "html",
    ".txt": "txt",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".webp": "image",
    ".xlsx": "xlsx",
    ".csv": "csv",
}

BACKEND_DOCUMENT_TYPES = {"noi_quy", "quy_trinh", "bieu_mau", "hoi_dap", "unknown"}
BACKEND_COLLECTION_STATUSES = {"link_collected", "collected", "downloaded", "missing", "failed"}
BACKEND_OCR_STATUSES = {"not_started", "processing", "done", "failed", "need_review"}
BACKEND_REVIEW_STATUSES = {"not_reviewed", "reviewing", "need_fix", "approved", "rejected"}
BACKEND_VALIDITY_STATUSES = {"unchecked", "valid", "expired", "replaced", "unknown"}
BACKEND_VERSION_ROLES = {"base", "replacement", "amendment", "supplement"}
BACKEND_RAG_STATUSES = {"not_indexed", "chunked", "embedded", "indexed", "published", "deactivated", "failed"}
BACKEND_CITATION_TYPES = {"page", "section", "paragraph"}
BACKEND_FILE_TYPES = {"pdf", "doc", "docx", "image", "xlsx", "pptx", "txt", "md", "html", "csv", "url", "youtube"}

OCR_METADATA_RE = re.compile(r"^\s*-\s*([^:]+):\s*(.*)\s*$")
RAW_OCR_REPORT_HEADER_RE = re.compile(
    r"\A\s*# PDF / Image Text Document\s*\n+## Metadata\s*\n+.*?^\s*## Extracted Text\s*$\s*",
    re.MULTILINE | re.DOTALL,
)
LAYOUT_ANALYZER_COMMENT_RE = re.compile(r"^\s*<!--\s*layout_analyzer:.*?-->\s*$\n?", re.MULTILINE)


@dataclass
class MetadataOptions:
    source_file: str | None = None
    ocr_status: str | None = None
    file_type: str | None = None
    language: str = "vi"
    document_type: str | None = None
    parser: str | None = None
    ocr_engine: str | None = None
    overwrite_auto: bool = False


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", without_marks)


def slugify(value: str) -> str:
    text = strip_accents(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "untitled"


def normalize_name(value: str) -> str:
    return slugify(value).replace("-", "")


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw_yaml = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            return parse_simple_yaml(raw_yaml), body.lstrip("\r\n")

    return {}, text


def parse_simple_yaml(raw_yaml: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in raw_yaml.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        list_match = re.match(r"^\s*-\s*(.*)$", line)
        if list_match and current_key:
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(parse_scalar(list_match.group(1).strip()))
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*(.*))?$", line)
        if not match:
            current_key = None
            continue

        key = match.group(1)
        value_text = match.group(2) if match.group(2) is not None else ""
        data[key] = parse_scalar(value_text.strip())
        current_key = key

    return data


def parse_scalar(value: str) -> Any:
    if value == "":
        return None
    if value == "[]":
        return []
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def yaml_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_.-]+", text):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_front_matter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key in FIELD_ORDER:
        value = metadata.get(key)
        if isinstance(value, list):
            if value:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {yaml_scalar(item)}")
            else:
                lines.append(f"{key}: []")
        else:
            if value is None:
                lines.append(f"{key}:")
            else:
                lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def checksum_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def resolve_existing_path(value: str | None, md_path: Path) -> Path | None:
    if not value:
        return None

    raw = value.strip().strip("`")
    if not raw:
        return None

    candidates = [Path(raw)]
    if not Path(raw).is_absolute():
        candidates.extend([NLCS_ROOT / raw, md_path.parent / raw, Path.cwd() / raw])

    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def parse_ocr_metadata(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    in_metadata = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "## Metadata":
            in_metadata = True
            continue
        if in_metadata and stripped.startswith("## ") and stripped != "## Metadata":
            break
        if not in_metadata:
            continue

        match = OCR_METADATA_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        value = match.group(2).strip().strip("`")
        result[key] = value
    return result


def source_candidates_from_md(md_path: Path, ocr_meta: dict[str, str]) -> list[str]:
    stems = [md_path.stem]
    for suffix in ["_structured", "_rag_clean", "_clean", "_output"]:
        if stems[0].lower().endswith(suffix):
            stems.append(stems[0][: -len(suffix)])
    if ocr_meta.get("source name"):
        stems.append(Path(ocr_meta["source name"]).stem)
    if ocr_meta.get("source file"):
        stems.append(Path(ocr_meta["source file"]).stem)
    return list(dict.fromkeys(normalize_name(stem) for stem in stems if stem))


def find_source_file(md_path: Path, existing: dict[str, Any], ocr_meta: dict[str, str], cli_source: str | None) -> Path | None:
    for value in [cli_source, existing.get("source_path"), existing.get("source_file"), ocr_meta.get("source file")]:
        found = resolve_existing_path(str(value), md_path) if value else None
        if found:
            return found

    attachment_root = NLCS_ROOT / "02_Attachments"
    if not attachment_root.exists():
        return None

    wanted = set(source_candidates_from_md(md_path, ocr_meta))
    for candidate in attachment_root.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in SOURCE_EXTS:
            if normalize_name(candidate.stem) in wanted:
                return candidate.resolve()
    return None


def path_for_metadata(path: Path) -> str:
    try:
        return path.resolve().relative_to(NLCS_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def detect_file_type(source_path: Path | None, existing: dict[str, Any], fallback: str | None) -> str:
    if fallback:
        return fallback
    if source_path:
        return FILE_TYPE_BY_EXT.get(source_path.suffix.lower(), source_path.suffix.lower().lstrip("."))
    existing_type = existing.get("file_type")
    return str(existing_type) if existing_type else ""


def generated_document_key(source_path: Path | None, md_path: Path) -> str:
    stem = source_path.stem if source_path else md_path.stem
    prefix_parts = ["ctu"]

    if source_path:
        parts = list(source_path.parts)
        lowered = [part.lower() for part in parts]
        if "pdfs" in lowered:
            index = lowered.index("pdfs")
            if index + 1 < len(parts):
                prefix_parts.append(slugify(parts[index + 1]))
        elif "docx" in lowered:
            index = lowered.index("docx")
            if index + 1 < len(parts):
                prefix_parts.append(slugify(parts[index + 1]))

    prefix_parts.append(slugify(stem))
    return "-".join(part for part in prefix_parts if part)


def generated_version_key(document_key: str, checksum: str) -> str:
    return f"{document_key}-{checksum[:12]}" if checksum else document_key


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if not is_empty(value):
            return value
    return None


def existing_value(existing: dict[str, Any], *keys: str) -> Any:
    return first_non_empty(*(existing.get(key) for key in keys))


def string_value(*values: Any) -> str:
    value = first_non_empty(*values)
    return str(value) if value is not None else ""


def normalize_enum(value: Any, allowed: set[str], default: str) -> str:
    if is_empty(value):
        return default
    text = str(value).strip()
    return text if text in allowed else default


def normalize_citation_type(value: Any) -> str:
    if str(value).strip() == "none":
        return "paragraph"
    return normalize_enum(value, BACKEND_CITATION_TYPES, "page")


def list_value(value: Any) -> list[Any]:
    if is_empty(value):
        return []
    if isinstance(value, list):
        return value
    return [value]


def source_file_name(source_path: Path | None, existing: dict[str, Any], ocr_meta: dict[str, str]) -> str:
    if source_path:
        return source_path.name

    raw = first_non_empty(existing.get("source_file"), ocr_meta.get("source file"), "")
    if not raw:
        return ""
    return Path(str(raw).strip().strip("`")).name


def source_path_value(source_path: Path | None, existing: dict[str, Any]) -> str | None:
    if source_path:
        return path_for_metadata(source_path)
    value = existing.get("source_path")
    return str(value) if not is_empty(value) else None


def infer_parser_from_ocr_metadata(ocr_meta: dict[str, str]) -> str | None:
    """Infer parser metadata from the generated OCR report header."""

    values = " ".join(str(v).lower() for v in ocr_meta.values())
    has_pymupdf = "pymupdf" in values
    has_llama = "llamaparse" in values or "llama" in values
    if has_pymupdf and has_llama:
        return "pymupdf_text_only+llamaparse"
    if has_llama:
        return "llamaparse"
    if has_pymupdf:
        return "pymupdf_text_only"
    return None


def infer_ocr_engine_from_ocr_metadata(ocr_meta: dict[str, str]) -> str | None:
    value = first_non_empty(ocr_meta.get("ocr engine for scan/images"), ocr_meta.get("ocr engine for scan pages/images"))
    if value:
        return str(value)
    values = " ".join(str(v).lower() for v in ocr_meta.values())
    if "llamaparse" in values or "llama" in values:
        return "LlamaParse API"
    return None


def looks_like_ocr_output(body: str, ocr_meta: dict[str, str]) -> bool:
    if ocr_meta:
        return True
    return "## Extracted Text" in body or "<!-- page:" in body or "<!-- extraction:" in body


def strip_generated_ocr_report_noise(body: str) -> str:
    """Remove internal OCR report metadata/debug lines from the user-facing Markdown body."""

    cleaned = RAW_OCR_REPORT_HEADER_RE.sub("", body, count=1)
    cleaned = LAYOUT_ANALYZER_COMMENT_RE.sub("", cleaned)
    return cleaned.lstrip("\r\n")


def build_metadata(
    md_path: Path,
    existing: dict[str, Any],
    body: str,
    args: MetadataOptions,
) -> dict[str, Any]:
    ocr_meta = parse_ocr_metadata(body)
    source_path = find_source_file(md_path, existing, ocr_meta, args.source_file)
    fallback_checksum = checksum_file(md_path) if md_path.exists() else checksum_text(body)
    checksum = checksum_file(source_path) if source_path else first_non_empty(ocr_meta.get("checksum"), existing.get("checksum"), fallback_checksum)
    document_key = first_non_empty(
        existing_value(existing, "document_key", "document_id"),
        generated_document_key(source_path, md_path),
    )
    old_checksum = existing.get("checksum") if isinstance(existing.get("checksum"), str) else ""
    current_version = existing_value(existing, "version_key", "version_id")
    auto_old_version = generated_version_key(str(document_key), old_checksum) if old_checksum else None
    if args.overwrite_auto or is_empty(current_version) or current_version == auto_old_version:
        version_key = generated_version_key(str(document_key), str(checksum or ""))
    else:
        version_key = current_version

    fallback_ocr_status = "done" if looks_like_ocr_output(body, ocr_meta) else "not_started"
    ocr_status = normalize_enum(
        first_non_empty(
            args.ocr_status,
            existing.get("ocr_status"),
            fallback_ocr_status,
        ),
        BACKEND_OCR_STATUSES,
        fallback_ocr_status,
    )

    raw_file_type = detect_file_type(source_path, existing, args.file_type)
    raw_document_type = first_non_empty(args.document_type, existing.get("document_type"))

    metadata: dict[str, Any] = {field: None for field in FIELD_ORDER}

    for field in HUMAN_STRING_FIELDS:
        metadata[field] = string_value(existing.get(field))
    for field in HUMAN_NULL_FIELDS:
        metadata[field] = existing.get(field) if not is_empty(existing.get(field)) else None

    metadata.update(
        {
            "document_key": document_key,
            "version_key": version_key,
            "document_type": normalize_enum(raw_document_type, BACKEND_DOCUMENT_TYPES, "unknown"),
            "audience": existing.get("audience") if not is_empty(existing.get("audience")) else ["student"],
            "version_label": string_value(existing.get("version_label"), existing.get("version")),
            "is_latest": existing.get("is_latest") if isinstance(existing.get("is_latest"), bool) else True,
            "validity_status": normalize_enum(existing.get("validity_status"), BACKEND_VALIDITY_STATUSES, "unchecked"),
            "version_role": normalize_enum(existing.get("version_role"), BACKEND_VERSION_ROLES, "base"),
            "replaces": list_value(existing.get("replaces")),
            "replaced_by": list_value(existing.get("replaced_by")),
            "amends": list_value(existing.get("amends")),
            "amended_by": list_value(existing.get("amended_by")),
            "supplements": list_value(existing.get("supplements")),
            "supplemented_by": list_value(existing.get("supplemented_by")),
            "collection_status": normalize_enum(existing.get("collection_status"), BACKEND_COLLECTION_STATUSES, "collected"),
            "ocr_status": ocr_status,
            "review_status": normalize_enum(existing.get("review_status"), BACKEND_REVIEW_STATUSES, "not_reviewed"),
            "rag_status": normalize_enum(existing.get("rag_status"), BACKEND_RAG_STATUSES, "not_indexed"),
            "source_file": source_file_name(source_path, existing, ocr_meta),
            "source_path": source_path_value(source_path, existing),
            "canonical_markdown_path": first_non_empty(existing.get("canonical_markdown_path"), path_for_metadata(md_path)),
            "file_type": normalize_enum(raw_file_type, BACKEND_FILE_TYPES, "md"),
            "language": string_value(args.language, existing.get("language"), "vi") or "vi",
            "citation_type": normalize_citation_type(first_non_empty(existing.get("citation_type"), "page")),
            "related_asset_keys": list_value(existing_value(existing, "related_asset_keys", "related_asset_ids")),
            "checksum": checksum,
            "parser": first_non_empty(args.parser, existing.get("parser"), infer_parser_from_ocr_metadata(ocr_meta)),
            "ocr_engine": first_non_empty(args.ocr_engine, existing.get("ocr_engine"), infer_ocr_engine_from_ocr_metadata(ocr_meta)),
            "created_at": first_non_empty(existing.get("created_at"), now_iso()),
            "updated_at": now_iso(),
            "notes": string_value(existing.get("notes")),
        }
    )

    return metadata


def iter_markdown_files(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == ".md" else []
    pattern = "**/*.md" if recursive else "*.md"
    return sorted(candidate for candidate in path.glob(pattern) if candidate.is_file())


def apply_to_file(md_path: Path, args: argparse.Namespace) -> bool:
    text = read_text(md_path)
    new_text = apply_metadata_to_markdown(
        text,
        md_path=md_path,
        source_file=args.source_file,
        ocr_status=args.ocr_status,
        file_type=args.file_type,
        language=args.language,
        document_type=args.document_type,
        overwrite_auto=args.overwrite_auto,
        parser=getattr(args, "parser", None),
        ocr_engine=getattr(args, "ocr_engine", None),
    )

    if args.dry_run:
        print(f"[DRY-RUN] {md_path}")
        return False

    md_path.write_text(new_text, encoding="utf-8", newline="\n")
    print(f"[OK] {md_path}")
    return True


def apply_metadata_to_markdown(
    markdown: str,
    md_path: str | Path,
    source_file: str | Path | None = None,
    ocr_status: str | None = None,
    file_type: str | None = None,
    language: str = "vi",
    document_type: str | None = None,
    overwrite_auto: bool = False,
    parser: str | None = None,
    ocr_engine: str | None = None,
) -> str:
    """Attach canonical YAML front matter to Markdown text.

    Only technical metadata is auto-filled. Fields that need human review stay
    empty unless the existing Markdown already has values or the caller passes
    explicit overrides.
    """

    existing, body = split_front_matter(markdown)
    options = MetadataOptions(
        source_file=str(source_file) if source_file else None,
        ocr_status=ocr_status,
        file_type=file_type,
        language=language,
        document_type=document_type,
        parser=parser,
        ocr_engine=ocr_engine,
        overwrite_auto=overwrite_auto,
    )
    metadata = build_metadata(Path(md_path), existing, body, options)
    body = strip_generated_ocr_report_noise(body)
    return dump_front_matter(metadata) + body


def apply_metadata_to_file(
    md_path: str | Path,
    source_file: str | Path | None = None,
    ocr_status: str | None = None,
    file_type: str | None = None,
    language: str = "vi",
    document_type: str | None = None,
    overwrite_auto: bool = False,
    parser: str | None = None,
    ocr_engine: str | None = None,
) -> Path:
    """Attach canonical YAML front matter to an existing Markdown file."""

    path = Path(md_path)
    updated = apply_metadata_to_markdown(
        read_text(path),
        md_path=path,
        source_file=source_file,
        ocr_status=ocr_status,
        file_type=file_type,
        language=language,
        document_type=document_type,
        parser=parser,
        ocr_engine=ocr_engine,
        overwrite_auto=overwrite_auto,
    )
    path.write_text(updated, encoding="utf-8", newline="\n")
    return path


def ap_dung_va_xac_thuc_metadata(
    markdown: str,
    output_path: str | Path,
    source_file: str | Path | None = None,
    language: str = "vi",
    **kw,
) -> str:
    """Gắn YAML front matter, xác thực và in lỗi/cảnh báo ra console.

    Dùng chung ở main.py, hybrid_page_router, hybrid_router và llamaparse_engine
    để tránh lặp pattern apply → validate → print ở 4 chỗ.
    Import validate_metadata_text cục bộ để tránh circular import.
    """
    try:
        from src.validation.validate_metadata import validate_metadata_text
    except ModuleNotFoundError:  # Allow direct execution from src/validation.
        from validate_metadata import validate_metadata_text

    md = apply_metadata_to_markdown(
        markdown, md_path=output_path, source_file=source_file,
        language=language, **kw,
    )
    errors, warnings = validate_metadata_text(md)
    visible_warnings = [w for w in warnings if not w.startswith("optional human field is empty:")]
    for e in errors:
        print(f"[METADATA ERROR] {output_path}: {e}")
    for w in visible_warnings:
        print(f"[METADATA WARN] {output_path}: {w}")
    if not errors:
        print(f"[METADATA OK] {output_path} errors=0 warnings={len(warnings)}")
    return md


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attach canonical YAML metadata to Markdown files.")
    parser.add_argument("path", help="Markdown file or directory.")
    parser.add_argument("--recursive", "-r", action="store_true", help="Process *.md recursively when path is a directory.")
    parser.add_argument("--source-file", help="Original source file used for checksum/source_file/source_path.")
    parser.add_argument("--ocr-status", choices=sorted(BACKEND_OCR_STATUSES))
    parser.add_argument("--file-type", choices=sorted(BACKEND_FILE_TYPES))
    parser.add_argument("--language", default="vi")
    parser.add_argument("--document-type", choices=sorted(BACKEND_DOCUMENT_TYPES), help="Optional human-reviewed document_type override.")
    parser.add_argument("--parser", help="Parser value to write into YAML metadata, e.g. pymupdf_text_only or llamaparse.")
    parser.add_argument("--ocr-engine", help="OCR engine value to write into YAML metadata, e.g. LlamaParse API.")
    parser.add_argument("--overwrite-auto", action="store_true", help="Refresh generated version_key and auto fields where possible.")
    parser.add_argument("--dry-run", action="store_true", help="Show files that would be changed without writing.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    target = Path(args.path)
    files = iter_markdown_files(target, args.recursive)
    if not files:
        print(f"[WARN] No Markdown files found: {target}")
        return 1

    changed = 0
    for md_path in files:
        changed += int(apply_to_file(md_path, args))

    print(f"[DONE] processed={len(files)} changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
