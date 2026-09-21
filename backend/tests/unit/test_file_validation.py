"""FR-KNW-001's own acceptance criterion: a security test proving a
malicious/malformed upload is rejected. `validate_file` is pure and
DB-free, so this is a plain unit test file, no fixtures needed.
"""

import pytest

from doda.domain.knowledge.file_validation import (
    FileContentMismatchError,
    FileTooLargeError,
    FileValidationError,
    InvalidFilenameError,
    UnsupportedFileTypeError,
    sanitize_filename,
    storage_key_for,
    validate_file,
)

_REAL_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nrest of a real pdf body"
_REAL_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_WINDOWS_PE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00rest of a windows executable"


def test_a_well_formed_pdf_is_accepted() -> None:
    content_type = validate_file(
        filename="report.pdf",
        declared_content_type="application/pdf",
        data=_REAL_PDF_BYTES,
        max_size_bytes=1_000_000,
    )
    assert content_type == "application/pdf"


def test_a_well_formed_png_is_accepted() -> None:
    content_type = validate_file(
        filename="chart.png",
        declared_content_type="image/png",
        data=_REAL_PNG_BYTES,
        max_size_bytes=1_000_000,
    )
    assert content_type == "image/png"


def test_a_plain_utf8_text_file_is_accepted() -> None:
    content_type = validate_file(
        filename="notes.txt",
        declared_content_type="text/plain",
        data=b"Salom, DODA!",
        max_size_bytes=1_000_000,
    )
    assert content_type == "text/plain"


def test_a_windows_executable_renamed_to_pdf_is_rejected() -> None:
    """The security-test acceptance criterion, made concrete: a Windows
    PE binary with a .pdf extension and a matching declared Content-Type
    must still be rejected, because its actual bytes are an executable,
    not a PDF."""
    with pytest.raises(FileContentMismatchError):
        validate_file(
            filename="invoice.pdf",
            declared_content_type="application/pdf",
            data=_WINDOWS_PE_BYTES,
            max_size_bytes=1_000_000,
        )


def test_an_elf_executable_renamed_to_a_supported_extension_is_rejected() -> None:
    elf_bytes = b"\x7fELF" + b"\x00" * 32
    with pytest.raises(FileContentMismatchError):
        validate_file(
            filename="photo.png",
            declared_content_type="image/png",
            data=elf_bytes,
            max_size_bytes=1_000_000,
        )


def test_a_shell_script_renamed_to_txt_is_rejected() -> None:
    with pytest.raises(FileContentMismatchError):
        validate_file(
            filename="notes.txt",
            declared_content_type="text/plain",
            data=b"#!/bin/sh\nrm -rf /\n",
            max_size_bytes=1_000_000,
        )


def test_a_file_larger_than_the_limit_is_rejected() -> None:
    with pytest.raises(FileTooLargeError):
        validate_file(
            filename="report.pdf",
            declared_content_type="application/pdf",
            data=_REAL_PDF_BYTES,
            max_size_bytes=len(_REAL_PDF_BYTES) - 1,
        )


def test_an_empty_file_is_rejected() -> None:
    with pytest.raises(FileValidationError):
        validate_file(
            filename="report.pdf", declared_content_type="application/pdf", data=b"", max_size_bytes=1_000_000
        )


def test_an_unsupported_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_file(
            filename="archive.zip",
            declared_content_type="application/zip",
            data=b"PK\x03\x04rest",
            max_size_bytes=1_000_000,
        )


def test_a_declared_content_type_that_does_not_match_the_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_file(
            filename="report.pdf",
            declared_content_type="image/png",
            data=_REAL_PDF_BYTES,
            max_size_bytes=1_000_000,
        )


def test_a_binary_blob_renamed_to_txt_is_rejected() -> None:
    with pytest.raises(FileContentMismatchError):
        validate_file(
            filename="notes.txt",
            declared_content_type="text/plain",
            data=b"\xff\xfe\x00\x01not valid utf-8: \x80\x81",
            max_size_bytes=1_000_000,
        )


@pytest.mark.parametrize("filename", ["../../etc/passwd.pdf", "a/b.pdf", "a\\b.pdf", "", "a" * 300 + ".pdf"])
def test_a_suspicious_or_malformed_filename_is_rejected(filename: str) -> None:
    with pytest.raises(InvalidFilenameError):
        sanitize_filename(filename)


def test_a_filename_with_no_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_file(
            filename="report",
            declared_content_type="application/pdf",
            data=_REAL_PDF_BYTES,
            max_size_bytes=1000,
        )


def test_storage_key_is_derived_only_from_server_generated_ids() -> None:
    import uuid

    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    document_id = uuid.uuid4()
    key = storage_key_for(customer_id=customer_id, workspace_id=workspace_id, document_id=document_id)
    assert key == f"{customer_id}/{workspace_id}/{document_id}"
