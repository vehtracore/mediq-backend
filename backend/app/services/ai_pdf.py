"""Validation for temporary PDF inputs used by AI chat."""

from io import BytesIO

from fastapi import HTTPException, UploadFile, status
from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_AI_PDF_BYTES = 8 * 1024 * 1024
MAX_AI_PDF_PAGES = 10
_PDF_HEADER_SCAN_BYTES = 1024
_SAFE_DOCUMENT_ERROR = "This PDF could not be processed."


def validate_ai_pdf_bytes(content: bytes) -> int:
    """Validate PDF structure and return its page count without extracting data."""
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_SAFE_DOCUMENT_ERROR,
        )

    header = content[:_PDF_HEADER_SCAN_BYTES].lstrip()
    if not header.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_SAFE_DOCUMENT_ERROR,
        )

    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_SAFE_DOCUMENT_ERROR,
            )
        page_count = len(reader.pages)
    except HTTPException:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, OSError, EOFError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_SAFE_DOCUMENT_ERROR,
        ) from None

    if page_count < 1 or page_count > MAX_AI_PDF_PAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_SAFE_DOCUMENT_ERROR,
        )
    return page_count


async def read_validated_ai_pdf(file: UploadFile) -> bytes:
    """Read a bounded multipart upload and validate it as a temporary PDF."""
    content = await file.read(MAX_AI_PDF_BYTES + 1)
    if len(content) > MAX_AI_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="This PDF is too large.",
        )
    validate_ai_pdf_bytes(content)
    return content
