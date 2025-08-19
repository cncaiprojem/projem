"""
Task 4.5: Invoice PDF rendering service with WeasyPrint (primary) and ReportLab (fallback).

Ultra-enterprise PDF generation with Turkish KVKK compliance and immutable storage.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple, Union
import os

from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..models.invoice import Invoice
from ..services.s3 import S3Service
from ..services.audit_service import AuditService

logger = get_logger(__name__)


class PDFGenerationError(Exception):
    """Raised when PDF generation fails."""

    pass


class PDFService:
    """
    Task 4.5: Ultra-enterprise PDF generation service.

    Features:
    - Primary: WeasyPrint with HTML/CSS templates
    - Fallback: ReportLab on WeasyPrint failure
    - MinIO storage with immutability
    - Audit logging with checksums
    - Turkish localization
    """

    def __init__(
        self, s3_service: S3Service, audit_service: AuditService, bucket_name: str = "invoices"
    ):
        self.s3_service = s3_service
        self.audit_service = audit_service
        self.bucket_name = bucket_name

    async def generate_invoice_pdf(
        self, db: Session, invoice: Invoice, force_regenerate: bool = False
    ) -> Tuple[str, str]:
        """
        Generate PDF for invoice and store in MinIO with immutability.

        Args:
            db: Database session for audit logging
            invoice: Invoice to generate PDF for
            force_regenerate: Force regeneration even if PDF exists

        Returns:
            Tuple of (pdf_url, checksum)

        Raises:
            PDFGenerationError: If both WeasyPrint and ReportLab fail
        """

        # Check if PDF already exists and not forcing regeneration
        if invoice.pdf_url and not force_regenerate:
            logger.info(
                f"PDF already exists for invoice {invoice.number}, returning stored object key"
            )
            # Return object key as first element (not presigned URL) for consistency
            return invoice.pdf_url, ""

        logger.info(f"Generating PDF for invoice {invoice.number}")

        # Generate PDF content using WeasyPrint (primary) or ReportLab (fallback)
        pdf_content = None
        renderer_used = None

        try:
            pdf_content = self._generate_with_weasyprint(invoice)
            renderer_used = "WeasyPrint"
            logger.info(f"Successfully generated PDF with WeasyPrint for invoice {invoice.number}")
        except Exception as e:
            logger.warning(f"WeasyPrint failed for invoice {invoice.number}: {e}")

            try:
                pdf_content = self._generate_with_reportlab(invoice)
                renderer_used = "ReportLab"
                logger.info(
                    f"Successfully generated PDF with ReportLab for invoice {invoice.number}"
                )
            except Exception as e2:
                logger.error(
                    f"Both WeasyPrint and ReportLab failed for invoice {invoice.number}: {e2}"
                )
                raise PDFGenerationError(f"PDF generation failed: WeasyPrint: {e}, ReportLab: {e2}")

        if not pdf_content:
            raise PDFGenerationError("PDF content is empty")

        # Calculate checksum for audit purposes
        checksum = hashlib.sha256(pdf_content).hexdigest()

        # Generate storage path: invoices/{YYYY}/{MM}/{invoice_number}.pdf
        issued_date = invoice.issued_at
        object_key = f"invoices/{issued_date.year:04d}/{issued_date.month:02d}/{invoice.number}.pdf"

        try:
            # Upload to MinIO with immutability settings
            await self._upload_pdf_to_storage(pdf_content, object_key, invoice.number, checksum)

            # Generate presigned URL (2 minute TTL as per requirement)
            pdf_url = await self.s3_service.get_presigned_url(
                bucket_name=self.bucket_name,
                object_key=object_key,
                expires_in=120,  # 2 minutes
            )

            # Update invoice with PDF URL (atomic transaction handling)
            # Note: We only update the invoice object here and let the calling context
            # handle the database transaction (commit/rollback). This ensures atomicity
            # of the entire operation including PDF generation and database update.
            invoice.pdf_url = object_key  # Store object key, not presigned URL

            # Audit log
            await self.audit_service.create_audit_entry(
                db=db,
                event_type="pdf_generated",
                user_id=invoice.user_id,
                scope_type="financial",
                scope_id=invoice.id,
                resource="invoice_pdf",
                payload={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.number,
                    "renderer": renderer_used,
                    "object_key": object_key,
                    "checksum": checksum,
                    "file_size": len(pdf_content),
                },
            )

            logger.info(f"PDF successfully generated and stored for invoice {invoice.number}")
            return pdf_url, checksum

        except Exception as e:
            logger.error(f"Failed to upload PDF for invoice {invoice.number}: {e}")
            raise PDFGenerationError(f"PDF upload failed: {e}")

    def _format_paid_status(self, paid_status) -> str:
        """
        Helper method to safely format paid status value.

        Handles both enum values and string representations with proper
        defensive programming to avoid AttributeError.

        Args:
            paid_status: The paid status from invoice (enum or string)

        Returns:
            Formatted uppercase string representation of status
        """
        if hasattr(paid_status, "value"):
            return str(paid_status.value).upper()
        return str(paid_status).upper()

    async def get_invoice_pdf_url(self, invoice: Invoice) -> Optional[str]:
        """
        Get presigned URL for existing invoice PDF.

        Args:
            invoice: Invoice to get PDF URL for

        Returns:
            Presigned URL or None if no PDF exists
        """
        if not invoice.pdf_url:
            return None

        try:
            # Generate fresh presigned URL (2 minute TTL)
            return await self.s3_service.get_presigned_url(
                bucket_name=self.bucket_name,
                object_key=invoice.pdf_url,
                expires_in=120,  # 2 minutes
            )
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for invoice {invoice.number}: {e}")
            return None

    def _generate_with_weasyprint(self, invoice: Invoice) -> bytes:
        """Generate PDF using WeasyPrint with HTML template."""
        try:
            import weasyprint
            from weasyprint import HTML, CSS
        except ImportError as e:
            raise PDFGenerationError(f"WeasyPrint not available: {e}")

        # Generate HTML content
        html_content = self._generate_invoice_html(invoice)

        # Generate CSS styling
        css_content = self._get_invoice_css()

        try:
            # Create WeasyPrint HTML object
            html_doc = HTML(string=html_content)
            css_doc = CSS(string=css_content)

            # Generate PDF
            pdf_content = html_doc.write_pdf(stylesheets=[css_doc])
            return pdf_content

        except Exception as e:
            raise PDFGenerationError(f"WeasyPrint rendering failed: {e}")

    def _generate_with_reportlab(self, invoice: Invoice) -> bytes:
        """Generate PDF using ReportLab as fallback."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        except ImportError as e:
            raise PDFGenerationError(f"ReportLab not available: {e}")

        temp_path = None
        try:
            # Create temporary file for PDF generation with proper context management
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as temp_file:
                temp_path = temp_file.name

            # Create PDF document
            doc = SimpleDocTemplate(
                temp_path,
                pagesize=A4,
                rightMargin=2 * cm,
                leftMargin=2 * cm,
                topMargin=2 * cm,
                bottomMargin=2 * cm,
            )

            # Build PDF content
            story = []
            styles = getSampleStyleSheet()

            # Title style
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Heading1"],
                fontSize=18,
                spaceAfter=30,
                alignment=TA_CENTER,
            )

            # Add title
            story.append(Paragraph("FATURA / INVOICE", title_style))
            story.append(Spacer(1, 20))

            # Invoice details
            invoice_data = [
                ["Fatura No / Invoice Number:", invoice.number],
                ["Tarih / Date:", invoice.issued_at.strftime("%d.%m.%Y")],
                ["Para Birimi / Currency:", invoice.currency],
                ["Durum / Status:", self._format_paid_status(invoice.paid_status)],
            ]

            invoice_table = Table(invoice_data, colWidths=[6 * cm, 6 * cm])
            invoice_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                    ]
                )
            )

            story.append(invoice_table)
            story.append(Spacer(1, 30))

            # Financial details
            financial_data = [
                ["Tutar / Amount:", f"{invoice.amount:.2f} {invoice.currency}"],
                ["KDV / VAT (20%):", f"{invoice.vat:.2f} {invoice.currency}"],
                ["Toplam / Total:", f"{invoice.total:.2f} {invoice.currency}"],
            ]

            financial_table = Table(financial_data, colWidths=[6 * cm, 6 * cm])
            financial_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 12),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                        ("BACKGROUND", (0, 2), (-1, 2), colors.yellow),  # Highlight total
                        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                    ]
                )
            )

            story.append(financial_table)

            # Build PDF
            doc.build(story)

            # Read generated PDF with proper error handling
            with open(temp_path, "rb") as pdf_file:
                pdf_content = pdf_file.read()

            return pdf_content

        except Exception as e:
            raise PDFGenerationError(f"ReportLab generation failed: {e}")
        finally:
            # Always clean up temporary file in finally block
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError as cleanup_error:
                    logger.warning(
                        f"Failed to clean up temporary file {temp_path}: {cleanup_error}"
                    )

    def _generate_invoice_html(self, invoice: Invoice) -> str:
        """Generate HTML template for invoice."""

        # Format dates for Turkish locale
        issued_date = invoice.issued_at.strftime("%d.%m.%Y")

        html_template = f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head>
            <meta charset="UTF-8">
            <title>Fatura {invoice.number}</title>
        </head>
        <body>
            <div class="invoice-container">
                <header class="invoice-header">
                    <h1>FATURA</h1>
                    <h2>INVOICE</h2>
                </header>
                
                <div class="invoice-details">
                    <div class="detail-row">
                        <span class="label">Fatura No / Invoice Number:</span>
                        <span class="value">{invoice.number}</span>
                    </div>
                    <div class="detail-row">
                        <span class="label">Tarih / Date:</span>
                        <span class="value">{issued_date}</span>
                    </div>
                    <div class="detail-row">
                        <span class="label">Para Birimi / Currency:</span>
                        <span class="value">{invoice.currency}</span>
                    </div>
                    <div class="detail-row">
                        <span class="label">Durum / Status:</span>
                        <span class="value status-{self._format_paid_status(invoice.paid_status).lower()}">{self._format_paid_status(invoice.paid_status)}</span>
                    </div>
                </div>
                
                <div class="financial-section">
                    <h3>Finansal Detaylar / Financial Details</h3>
                    <div class="amount-table">
                        <div class="amount-row">
                            <span class="amount-label">Tutar / Amount:</span>
                            <span class="amount-value">{invoice.amount:.2f} {invoice.currency}</span>
                        </div>
                        <div class="amount-row">
                            <span class="amount-label">KDV / VAT (20%):</span>
                            <span class="amount-value">{invoice.vat:.2f} {invoice.currency}</span>
                        </div>
                        <div class="amount-row total-row">
                            <span class="amount-label">Toplam / Total:</span>
                            <span class="amount-value">{invoice.total:.2f} {invoice.currency}</span>
                        </div>
                    </div>
                </div>
                
                <footer class="invoice-footer">
                    <p>Bu fatura elektronik ortamda oluşturulmuştur.</p>
                    <p>This invoice was generated electronically.</p>
                </footer>
            </div>
        </body>
        </html>
        """

        return html_template

    def _get_invoice_css(self) -> str:
        """Get CSS styling for invoice PDF."""

        css_content = """
        @page {
            size: A4;
            margin: 2cm;
        }
        
        body {
            font-family: Arial, sans-serif;
            font-size: 12pt;
            line-height: 1.4;
            color: #333;
        }
        
        .invoice-container {
            max-width: 100%;
            margin: 0 auto;
        }
        
        .invoice-header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #333;
            padding-bottom: 20px;
        }
        
        .invoice-header h1 {
            font-size: 24pt;
            margin: 0;
            color: #333;
        }
        
        .invoice-header h2 {
            font-size: 18pt;
            margin: 5px 0 0 0;
            color: #666;
            font-weight: normal;
        }
        
        .invoice-details {
            margin-bottom: 30px;
        }
        
        .detail-row {
            display: flex;
            margin-bottom: 10px;
            padding: 8px;
            border-bottom: 1px solid #eee;
        }
        
        .detail-row:nth-child(even) {
            background-color: #f9f9f9;
        }
        
        .label {
            flex: 1;
            font-weight: bold;
            color: #555;
        }
        
        .value {
            flex: 1;
            text-align: right;
        }
        
        .status-paid {
            color: #28a745;
            font-weight: bold;
        }
        
        .status-unpaid {
            color: #dc3545;
            font-weight: bold;
        }
        
        .status-pending {
            color: #ffc107;
            font-weight: bold;
        }
        
        .financial-section {
            margin-bottom: 30px;
        }
        
        .financial-section h3 {
            font-size: 16pt;
            margin-bottom: 15px;
            color: #333;
            border-bottom: 1px solid #333;
            padding-bottom: 5px;
        }
        
        .amount-table {
            border: 1px solid #333;
        }
        
        .amount-row {
            display: flex;
            padding: 12px;
            border-bottom: 1px solid #ddd;
        }
        
        .amount-row:last-child {
            border-bottom: none;
        }
        
        .total-row {
            background-color: #f0f0f0;
            font-weight: bold;
            font-size: 14pt;
            border-top: 2px solid #333;
        }
        
        .amount-label {
            flex: 1;
            font-weight: bold;
        }
        
        .amount-value {
            flex: 1;
            text-align: right;
            font-family: 'Courier New', monospace;
        }
        
        .invoice-footer {
            margin-top: 40px;
            text-align: center;
            font-size: 10pt;
            color: #666;
            border-top: 1px solid #ccc;
            padding-top: 20px;
        }
        
        .invoice-footer p {
            margin: 5px 0;
        }
        """

        return css_content

    async def _upload_pdf_to_storage(
        self, pdf_content: bytes, object_key: str, invoice_number: str, checksum: str
    ) -> None:
        """Upload PDF to MinIO with immutability settings."""

        try:
            # Set metadata for immutability and audit
            metadata = {
                "Content-Type": "application/pdf",
                "X-Invoice-Number": invoice_number,
                "X-Generated-At": datetime.utcnow().isoformat(),
                "X-Checksum": checksum,
                "X-Immutable": "true",
            }

            # Upload to MinIO
            await self.s3_service.upload_file_content(
                bucket_name=self.bucket_name,
                object_key=object_key,
                content=pdf_content,
                content_type="application/pdf",
                metadata=metadata,
            )

            # Set object immutability (legal hold) - if supported by MinIO
            try:
                await self.s3_service.set_object_legal_hold(
                    bucket_name=self.bucket_name, object_key=object_key, legal_hold=True
                )
                logger.info(f"Legal hold set for PDF {object_key}")
            except Exception as e:
                logger.warning(f"Could not set legal hold for {object_key}: {e}")
                # Continue without legal hold - not all MinIO configurations support it

            logger.info(f"PDF uploaded successfully: {object_key}")

        except Exception as e:
            logger.error(f"Failed to upload PDF {object_key}: {e}")
            raise
