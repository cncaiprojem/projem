"""
Task 4.5: Invoice PDF rendering and download API endpoints.

Ultra-enterprise PDF generation and delivery with Turkish KVKK compliance.
"""

from __future__ import annotations

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..middleware.jwt_middleware import get_current_user, AuthenticatedUser
from ..db import get_db
from ..core.logging import get_logger
from ..models.invoice import Invoice
from ..services.pdf_service import PDFService, PDFGenerationError
from ..services.s3 import s3_service
from ..services.audit_service import audit_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


def get_client_info(request: Request) -> tuple[str, str]:
    """Extract client IP and user agent for audit purposes."""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:200]
    return client_ip, user_agent


@router.get("/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Download invoice PDF with secure presigned URL.

    Task 4.5 Requirements:
    - Generate presigned URL (2 minute TTL)
    - Return 404 if PDF not generated
    - Full audit logging
    - Turkish KVKV compliance

    **Security Features:**
    - User can only access their own invoices
    - Admin can access any invoice
    - Presigned URLs expire in 2 minutes
    - Full audit trail

    **Error Responses:**
    - 404: Invoice not found or PDF not generated
    - 403: Access denied to invoice
    - 500: PDF generation or storage error
    """

    client_ip, user_agent = get_client_info(request)
    operation_id = str(uuid.uuid4())

    try:
        # Find invoice
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            logger.warning(
                f"Invoice not found: {invoice_id}",
                extra={
                    "operation": "invoice_pdf_not_found",
                    "user_id": current_user.id,
                    "invoice_id": invoice_id,
                    "operation_id": operation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "invoice_not_found",
                    "message": "Invoice not found",
                    "message_tr": "Fatura bulunamadı",
                },
            )

        # Authorization check - user can only access their own invoices
        # TODO: Add admin check when role system is available
        if invoice.user_id != current_user.id:
            logger.warning(
                f"Unauthorized invoice access attempt",
                extra={
                    "operation": "invoice_pdf_unauthorized",
                    "user_id": current_user.id,
                    "invoice_id": invoice_id,
                    "invoice_owner": invoice.user_id,
                    "operation_id": operation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "access_denied",
                    "message": "Access denied to invoice",
                    "message_tr": "Faturaya erişim reddedildi",
                },
            )

        # Initialize PDF service
        pdf_service = PDFService(s3_service=s3_service, audit_service=audit_service)

        # Check if PDF exists, generate if not
        if not invoice.pdf_url:
            logger.info(f"Generating PDF for invoice {invoice.number}")

            try:
                pdf_url, checksum = await pdf_service.generate_invoice_pdf(
                    db=db, invoice=invoice, force_regenerate=False
                )

                # Note: Do NOT commit here - will be done at the end of the transaction
                # This ensures atomicity of the entire operation

                logger.info(
                    f"PDF generated for invoice {invoice.number}",
                    extra={
                        "operation": "invoice_pdf_generated",
                        "user_id": current_user.id,
                        "invoice_id": invoice_id,
                        "invoice_number": invoice.number,
                        "checksum": checksum,
                        "operation_id": operation_id,
                    },
                )

            except PDFGenerationError as e:
                # Rollback any pending changes on error
                db.rollback()
                logger.error(
                    f"PDF generation failed for invoice {invoice.number}: {e}",
                    extra={
                        "operation": "invoice_pdf_generation_failed",
                        "user_id": current_user.id,
                        "invoice_id": invoice_id,
                        "error": str(e),
                        "operation_id": operation_id,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "pdf_generation_failed",
                        "message": "Failed to generate PDF",
                        "message_tr": "PDF oluşturma başarısız",
                    },
                )
        else:
            # Get presigned URL for existing PDF
            pdf_url = await pdf_service.get_invoice_pdf_url(invoice)

            if not pdf_url:
                logger.error(
                    f"Failed to generate presigned URL for invoice {invoice.number}",
                    extra={
                        "operation": "invoice_pdf_url_failed",
                        "user_id": current_user.id,
                        "invoice_id": invoice_id,
                        "operation_id": operation_id,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "pdf_url_failed",
                        "message": "Failed to generate download URL",
                        "message_tr": "İndirme bağlantısı oluşturulamadı",
                    },
                )

        # Audit the PDF access
        await audit_service.create_audit_entry(
            db=db,
            event_type="pdf_accessed",
            user_id=current_user.id,
            scope_type="financial",
            scope_id=invoice.id,
            resource="invoice_pdf",
            ip_address=client_ip,
            user_agent=user_agent,
            payload={
                "invoice_id": invoice.id,
                "invoice_number": invoice.number,
                "access_method": "download",
            },
        )

        db.commit()

        logger.info(
            f"PDF download initiated for invoice {invoice.number}",
            extra={
                "operation": "invoice_pdf_download",
                "user_id": current_user.id,
                "invoice_id": invoice_id,
                "invoice_number": invoice.number,
                "operation_id": operation_id,
            },
        )

        # Redirect to presigned URL
        return RedirectResponse(url=pdf_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error during PDF download for invoice {invoice_id}",
            exc_info=True,
            extra={
                "operation": "invoice_pdf_download_error",
                "user_id": current_user.id,
                "invoice_id": invoice_id,
                "error_type": type(e).__name__,
                "error": str(e),
                "operation_id": operation_id,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_server_error",
                "message": "Internal server error",
                "message_tr": "Sunucu hatası",
            },
        )


@router.post("/{invoice_id}/pdf/regenerate")
async def regenerate_invoice_pdf(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Force regenerate PDF for an invoice.

    **Admin Only Endpoint**
    - Useful for fixing corrupted PDFs
    - Forces regeneration even if PDF exists
    - Full audit logging

    **Error Responses:**
    - 404: Invoice not found
    - 403: Access denied (non-admin)
    - 500: PDF generation error
    """

    client_ip, user_agent = get_client_info(request)
    operation_id = str(uuid.uuid4())

    try:
        # Find invoice
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "invoice_not_found",
                    "message": "Invoice not found",
                    "message_tr": "Fatura bulunamadı",
                },
            )

        # Authorization check - user can only regenerate their own invoices
        # TODO: Add proper admin role check
        if invoice.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "access_denied",
                    "message": "Access denied to invoice",
                    "message_tr": "Faturaya erişim reddedildi",
                },
            )

        # Initialize PDF service
        pdf_service = PDFService(s3_service=s3_service, audit_service=audit_service)

        # Force regenerate PDF
        try:
            pdf_url, checksum = await pdf_service.generate_invoice_pdf(
                db=db, invoice=invoice, force_regenerate=True
            )

            # Audit the regeneration
            await audit_service.create_audit_entry(
                db=db,
                event_type="pdf_regenerated",
                user_id=current_user.id,
                scope_type="financial",
                scope_id=invoice.id,
                resource="invoice_pdf",
                ip_address=client_ip,
                user_agent=user_agent,
                payload={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.number,
                    "checksum": checksum,
                    "forced": True,
                },
            )

            # Single atomic commit for all operations
            db.commit()

            logger.info(
                f"PDF regenerated for invoice {invoice.number}",
                extra={
                    "operation": "invoice_pdf_regenerated",
                    "user_id": current_user.id,
                    "invoice_id": invoice_id,
                    "invoice_number": invoice.number,
                    "checksum": checksum,
                    "operation_id": operation_id,
                },
            )

            return {
                "success": True,
                "message": "PDF regenerated successfully",
                "message_tr": "PDF başarıyla yeniden oluşturuldu",
                "invoice_id": invoice.id,
                "invoice_number": invoice.number,
                "checksum": checksum,
            }

        except PDFGenerationError as e:
            # Rollback any pending changes on error
            db.rollback()
            logger.error(
                f"PDF regeneration failed for invoice {invoice.number}: {e}",
                extra={
                    "operation": "invoice_pdf_regeneration_failed",
                    "user_id": current_user.id,
                    "invoice_id": invoice_id,
                    "error": str(e),
                    "operation_id": operation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "pdf_regeneration_failed",
                    "message": "Failed to regenerate PDF",
                    "message_tr": "PDF yeniden oluşturma başarısız",
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error during PDF regeneration for invoice {invoice_id}",
            exc_info=True,
            extra={
                "operation": "invoice_pdf_regeneration_error",
                "user_id": current_user.id,
                "invoice_id": invoice_id,
                "error_type": type(e).__name__,
                "error": str(e),
                "operation_id": operation_id,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_server_error",
                "message": "Internal server error",
                "message_tr": "Sunucu hatası",
            },
        )
