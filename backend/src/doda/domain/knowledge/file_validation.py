"""FR-KNW-001: "PDF/DOCX/XLSX/TXT/rasm turlari; hajm va tur tekshiruvi;
zararli fayl (malware) validatsiyasi" — file-type/size validation for
ingest. This is NOT an antivirus scanner (no such capability exists in
this sandbox or codebase, and building a fake one would violate the
Master Instruction against claiming untested security guarantees);
"malware validation" here means the concrete, checkable thing this layer
actually can enforce: a file's ACTUAL bytes must match what its
extension and declared content-type claim, and a small set of
unambiguous executable/script signatures are rejected outright
regardless of extension — the classic "renamed .exe" bypass this
requirement's own acceptance criterion (a security test) targets.
"""

import uuid

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TXT = "text/plain"
PNG = "image/png"
JPEG = "image/jpeg"

_EXTENSION_CONTENT_TYPES: dict[str, str] = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".xlsx": XLSX,
    ".txt": TXT,
    ".png": PNG,
    ".jpg": JPEG,
    ".jpeg": JPEG,
}

# DOCX/XLSX are both OOXML-in-a-ZIP-container — a full OOXML content-type
# check (parsing the central directory for "word/"/"xl/" entries) is a
# real, known gap this v1 does not close; both accept any well-formed ZIP
# signature. Documented in CLAUDE.md/docs/risk-register.md, not silently
# assumed away.
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    PDF: (b"%PDF-",),
    DOCX: _ZIP_MAGIC,
    XLSX: _ZIP_MAGIC,
    PNG: (b"\x89PNG\r\n\x1a\n",),
    JPEG: (b"\xff\xd8\xff",),
}

# Unambiguous executable/script signatures — rejected for EVERY declared
# type, not only ones they wouldn't otherwise match, because a hit here
# means "this is executable content" independent of whatever extension
# or Content-Type header the caller attached to it. This is the specific
# check the security-test acceptance criterion exercises: a Windows PE
# binary renamed to "invoice.pdf" is rejected here even though a ".pdf"
# extension and "application/pdf" declared type would otherwise be
# accepted at the extension-mapping step above.
_EXECUTABLE_SIGNATURES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE / DOS executable
    b"\x7fELF",  # Linux ELF executable
    b"#!",  # Unix shebang script
)

MAX_FILENAME_LENGTH = 255


class FileValidationError(Exception):
    """Base class for every rejection this module raises — callers
    (knowledge_service, api/knowledge.py) catch this one type and turn
    it into a single 422 response, the same one-shape-per-category
    pattern api/errors.py uses for every other domain."""


class FileTooLargeError(FileValidationError):
    pass


class InvalidFilenameError(FileValidationError):
    pass


class UnsupportedFileTypeError(FileValidationError):
    pass


class FileContentMismatchError(FileValidationError):
    """The file's actual bytes don't match what its extension/declared
    content-type claim to be — this is what catches a renamed
    executable or a truncated/corrupted upload."""


def sanitize_filename(filename: str) -> str:
    """`filename` is a display name (Document.filename) — it is never
    used as an actual filesystem path (LocalFilesystemObjectStorage
    hashes the storage key instead, see its own docstring), but a value
    with no sane reading as a single file's name is refused outright
    rather than silently collapsed to a basename."""
    if not filename or filename in {".", ".."}:
        raise InvalidFilenameError("filename is empty")
    if len(filename) > MAX_FILENAME_LENGTH:
        raise InvalidFilenameError("filename is too long")
    if "\x00" in filename:
        raise InvalidFilenameError("filename contains a NUL byte")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise InvalidFilenameError("filename must not contain a path segment")
    return filename


def _extension_of(filename: str) -> str:
    suffix_index = filename.rfind(".")
    if suffix_index <= 0:
        raise UnsupportedFileTypeError(f"{filename!r} has no recognizable file extension")
    return filename[suffix_index:].lower()


def validate_file(*, filename: str, declared_content_type: str, data: bytes, max_size_bytes: int) -> str:
    """Returns the confirmed content type on success; raises a
    FileValidationError subclass otherwise. Order matters: the cheap
    checks (size, filename shape) run before the extension/content-type/
    magic-byte cross-check, so a malformed filename never even reaches
    the byte-signature scan."""
    if len(data) == 0:
        raise FileValidationError("uploaded file is empty")
    if len(data) > max_size_bytes:
        raise FileTooLargeError(f"file is {len(data)} bytes, exceeds the {max_size_bytes}-byte limit")

    filename = sanitize_filename(filename)
    extension = _extension_of(filename)
    expected_type = _EXTENSION_CONTENT_TYPES.get(extension)
    if expected_type is None:
        raise UnsupportedFileTypeError(f"file extension {extension!r} is not an allowed type")
    if declared_content_type != expected_type:
        raise UnsupportedFileTypeError(
            f"declared content-type {declared_content_type!r} does not match extension "
            f"{extension!r} (expected {expected_type!r})"
        )

    if any(data.startswith(signature) for signature in _EXECUTABLE_SIGNATURES):
        raise FileContentMismatchError(
            f"file content looks like an executable or script, not {expected_type!r}"
        )

    signatures = _MAGIC_SIGNATURES.get(expected_type)
    if signatures is not None:
        if not any(data.startswith(signature) for signature in signatures):
            raise FileContentMismatchError(
                f"file content does not match the {expected_type!r} signature its extension declares"
            )
    else:
        # text/plain has no fixed magic byte — the file must at least
        # decode as UTF-8 text; a binary blob renamed to .txt fails this.
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise FileContentMismatchError("file declared as text/plain is not valid UTF-8 text") from None

    return expected_type


def storage_key_for(*, customer_id: uuid.UUID, workspace_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """An opaque object-storage key — LocalFilesystemObjectStorage hashes
    it into a path itself (defense in depth), but this is still built
    entirely from server-generated ids, never from caller-supplied
    filename text."""
    return f"{customer_id}/{workspace_id}/{document_id}"
