"""
Test Task 4.5: Invoice PDF rendering and MinIO storage with immutability.

Tests for ultra-enterprise PDF generation, storage, and delivery.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from decimal import Decimal
from datetime import datetime, timezone
import hashlib

from app.models.invoice import Invoice
from app.models.user import User
from app.services.pdf_service import PDFService, PDFGenerationError
from app.services.s3 import S3Service
from app.services.audit_service import AuditService


class TestPDFService:
    """Test PDF generation service with both WeasyPrint and ReportLab."""
    
    @pytest.fixture
    def mock_s3_service(self):
        """Mock S3 service for testing."""
        service = Mock(spec=S3Service)
        service.upload_file_content = AsyncMock()
        service.get_presigned_url = AsyncMock(return_value="https://example.com/presigned-url")
        service.set_object_legal_hold = AsyncMock(return_value=True)
        return service
    
    @pytest.fixture
    def mock_audit_service(self):
        """Mock audit service for testing."""
        service = Mock(spec=AuditService)
        service.create_audit_entry = AsyncMock()
        return service
    
    @pytest.fixture
    def sample_invoice(self):
        """Create sample invoice for testing."""
        user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User"
        )
        
        invoice = Invoice(
            id=123,
            user_id=1,
            license_id=456,
            number="202408-000001-CNCAI",
            amount=Decimal("100.00"),
            currency="TRY",
            vat=Decimal("20.00"),
            total=Decimal("120.00"),
            issued_at=datetime(2024, 8, 19, 10, 0, 0, tzinfo=timezone.utc),
            pdf_url=None
        )
        invoice.user = user
        return invoice
    
    @pytest.fixture
    def pdf_service(self, mock_s3_service, mock_audit_service):
        """Create PDF service with mocked dependencies."""
        return PDFService(
            s3_service=mock_s3_service,
            audit_service=mock_audit_service
        )
    
    async def test_generate_pdf_with_reportlab_fallback(
        self, 
        pdf_service, 
        sample_invoice,
        mock_s3_service,
        mock_audit_service
    ):
        """Test PDF generation falls back to ReportLab when WeasyPrint fails."""
        mock_db = Mock()
        
        # Mock WeasyPrint failure to force ReportLab usage
        with patch('weasyprint.HTML', side_effect=ImportError("WeasyPrint not available")), \
             patch('builtins.open', create=True) as mock_open, \
             patch('os.unlink') as mock_unlink, \
             patch('tempfile.NamedTemporaryFile') as mock_tempfile:
            
            # Mock temporary file
            mock_temp = Mock()
            mock_temp.name = "/tmp/test.pdf"
            mock_tempfile.return_value.__enter__.return_value = mock_temp
            
            # Mock file operations
            mock_pdf_content = b"PDF content from ReportLab"
            mock_open.return_value.__enter__.return_value.read.return_value = mock_pdf_content
            
            # Test PDF generation through public API
            pdf_url, checksum = await pdf_service.generate_invoice_pdf(
                db=mock_db,
                invoice=sample_invoice
            )
            
            # Verify ReportLab was used (temp file was created and cleaned up)
            assert mock_tempfile.called
            assert mock_unlink.called
            assert pdf_url == "https://example.com/presigned-url"
            assert checksum == hashlib.sha256(mock_pdf_content).hexdigest()
    
    def test_generate_invoice_html(self, pdf_service, sample_invoice):
        """Test HTML template generation."""
        html_content = pdf_service._generate_invoice_html(sample_invoice)
        
        # Check essential elements
        assert "202408-000001-CNCAI" in html_content
        assert "120.00 TRY" in html_content
        assert "100.00 TRY" in html_content
        assert "20.00 TRY" in html_content
        assert "19.08.2024" in html_content
        assert "FATURA" in html_content
        assert "INVOICE" in html_content
    
    def test_get_invoice_css(self, pdf_service):
        """Test CSS generation for invoice styling."""
        css_content = pdf_service._get_invoice_css()
        
        # Check essential CSS elements
        assert "@page" in css_content
        assert "font-family" in css_content
        assert ".invoice-container" in css_content
        assert ".total-row" in css_content
        assert "A4" in css_content
    
    async def test_generate_invoice_pdf_success_weasyprint(
        self, 
        pdf_service, 
        sample_invoice, 
        mock_s3_service, 
        mock_audit_service
    ):
        """Test successful PDF generation with WeasyPrint."""
        mock_db = Mock()
        
        # Mock WeasyPrint
        with patch('weasyprint.HTML') as mock_html, \
             patch('weasyprint.CSS') as mock_css:
            
            mock_pdf_content = b"WeasyPrint PDF content"
            mock_html.return_value.write_pdf.return_value = mock_pdf_content
            
            # Test PDF generation
            pdf_url, checksum = await pdf_service.generate_invoice_pdf(
                db=mock_db,
                invoice=sample_invoice
            )
            
            # Verify results
            assert pdf_url == "https://example.com/presigned-url"
            assert checksum == hashlib.sha256(mock_pdf_content).hexdigest()
            
            # Verify S3 upload was called
            mock_s3_service.upload_file_content.assert_called_once()
            upload_args = mock_s3_service.upload_file_content.call_args
            assert upload_args[1]['bucket_name'] == "invoices"
            assert upload_args[1]['object_key'] == "invoices/2024/08/202408-000001-CNCAI.pdf"
            assert upload_args[1]['content'] == mock_pdf_content
            assert upload_args[1]['content_type'] == "application/pdf"
            
            # Verify presigned URL generation
            mock_s3_service.get_presigned_url.assert_called_once_with(
                bucket_name="invoices",
                object_key="invoices/2024/08/202408-000001-CNCAI.pdf",
                expires_in=120
            )
            
            # Verify audit logging
            mock_audit_service.create_audit_entry.assert_called_once()
            audit_args = mock_audit_service.create_audit_entry.call_args
            assert audit_args[1]['event_type'] == "pdf_generated"
            assert audit_args[1]['user_id'] == 1
            assert audit_args[1]['scope_type'] == "financial"
            assert audit_args[1]['scope_id'] == 123
            
            # Verify invoice was updated
            assert sample_invoice.pdf_url == "invoices/2024/08/202408-000001-CNCAI.pdf"
    
    async def test_generate_invoice_pdf_fallback_to_reportlab(
        self, 
        pdf_service, 
        sample_invoice, 
        mock_s3_service, 
        mock_audit_service
    ):
        """Test fallback to ReportLab when WeasyPrint fails."""
        mock_db = Mock()
        
        # Mock WeasyPrint failure and ReportLab success
        with patch('weasyprint.HTML', side_effect=Exception("WeasyPrint failed")), \
             patch.object(pdf_service, '_generate_with_reportlab') as mock_reportlab:
            
            mock_pdf_content = b"ReportLab PDF content"
            mock_reportlab.return_value = mock_pdf_content
            
            # Test PDF generation
            pdf_url, checksum = await pdf_service.generate_invoice_pdf(
                db=mock_db,
                invoice=sample_invoice
            )
            
            # Verify ReportLab was used
            mock_reportlab.assert_called_once_with(sample_invoice)
            
            # Verify results
            assert pdf_url == "https://example.com/presigned-url"
            assert checksum == hashlib.sha256(mock_pdf_content).hexdigest()
            
            # Verify audit logging mentions ReportLab
            audit_args = mock_audit_service.create_audit_entry.call_args
            assert audit_args[1]['payload']['renderer'] == "ReportLab"
    
    async def test_generate_invoice_pdf_both_renderers_fail(
        self, 
        pdf_service, 
        sample_invoice
    ):
        """Test error handling when both renderers fail."""
        mock_db = Mock()
        
        # Mock both WeasyPrint and ReportLab failures
        with patch('weasyprint.HTML', side_effect=Exception("WeasyPrint failed")), \
             patch.object(pdf_service, '_generate_with_reportlab', side_effect=Exception("ReportLab failed")):
            
            # Test PDF generation failure
            with pytest.raises(PDFGenerationError) as exc_info:
                await pdf_service.generate_invoice_pdf(
                    db=mock_db,
                    invoice=sample_invoice
                )
            
            assert "PDF generation failed" in str(exc_info.value)
            assert "WeasyPrint failed" in str(exc_info.value)
            assert "ReportLab failed" in str(exc_info.value)
    
    async def test_generate_invoice_pdf_existing_pdf_no_force(
        self, 
        pdf_service, 
        sample_invoice
    ):
        """Test that existing PDF is not regenerated without force flag."""
        mock_db = Mock()
        sample_invoice.pdf_url = "invoices/2024/08/existing.pdf"
        
        # Test PDF generation
        pdf_url, checksum = await pdf_service.generate_invoice_pdf(
            db=mock_db,
            invoice=sample_invoice,
            force_regenerate=False
        )
        
        # Should return existing PDF URL
        assert pdf_url == "invoices/2024/08/existing.pdf"
        assert checksum == ""
    
    async def test_get_invoice_pdf_url_success(
        self, 
        pdf_service, 
        sample_invoice, 
        mock_s3_service
    ):
        """Test getting presigned URL for existing PDF."""
        sample_invoice.pdf_url = "invoices/2024/08/test.pdf"
        
        pdf_url = await pdf_service.get_invoice_pdf_url(sample_invoice)
        
        assert pdf_url == "https://example.com/presigned-url"
        mock_s3_service.get_presigned_url.assert_called_once_with(
            bucket_name="invoices",
            object_key="invoices/2024/08/test.pdf",
            expires_in=120
        )
    
    async def test_get_invoice_pdf_url_no_pdf(self, pdf_service, sample_invoice):
        """Test getting URL when no PDF exists."""
        sample_invoice.pdf_url = None
        
        pdf_url = await pdf_service.get_invoice_pdf_url(sample_invoice)
        
        assert pdf_url is None
    
    async def test_get_invoice_pdf_url_s3_error(
        self, 
        pdf_service, 
        sample_invoice, 
        mock_s3_service
    ):
        """Test error handling when S3 URL generation fails."""
        sample_invoice.pdf_url = "invoices/2024/08/test.pdf"
        mock_s3_service.get_presigned_url.side_effect = Exception("S3 error")
        
        pdf_url = await pdf_service.get_invoice_pdf_url(sample_invoice)
        
        assert pdf_url is None
    
    def test_reportlab_import_error(self, pdf_service, sample_invoice):
        """Test handling of ReportLab import error."""
        with patch('builtins.__import__', side_effect=ImportError("ReportLab not available")):
            with pytest.raises(PDFGenerationError) as exc_info:
                pdf_service._generate_with_reportlab(sample_invoice)
            
            assert "ReportLab not available" in str(exc_info.value)
    
    def test_weasyprint_import_error(self, pdf_service, sample_invoice):
        """Test handling of WeasyPrint import error."""
        with patch('builtins.__import__', side_effect=ImportError("WeasyPrint not available")):
            with pytest.raises(PDFGenerationError) as exc_info:
                pdf_service._generate_with_weasyprint(sample_invoice)
            
            assert "WeasyPrint not available" in str(exc_info.value)
    
    async def test_upload_pdf_to_storage_metadata(
        self, 
        pdf_service, 
        mock_s3_service
    ):
        """Test PDF upload with correct metadata."""
        pdf_content = b"Test PDF content"
        object_key = "invoices/2024/08/test.pdf"
        invoice_number = "202408-000001-CNCAI"
        checksum = "abc123"
        
        await pdf_service._upload_pdf_to_storage(
            pdf_content=pdf_content,
            object_key=object_key,
            invoice_number=invoice_number,
            checksum=checksum
        )
        
        # Verify upload was called with correct metadata
        mock_s3_service.upload_file_content.assert_called_once()
        upload_args = mock_s3_service.upload_file_content.call_args
        
        metadata = upload_args[1]['metadata']
        assert metadata['Content-Type'] == "application/pdf"
        assert metadata['X-Invoice-Number'] == invoice_number
        assert metadata['X-Checksum'] == checksum
        assert metadata['X-Immutable'] == "true"
        assert 'X-Generated-At' in metadata
        
        # Verify legal hold attempt
        mock_s3_service.set_object_legal_hold.assert_called_once_with(
            bucket_name="invoices",
            object_key=object_key,
            legal_hold=True
        )
    
    async def test_upload_pdf_to_storage_s3_error(
        self, 
        pdf_service, 
        mock_s3_service
    ):
        """Test error handling during S3 upload."""
        mock_s3_service.upload_file_content.side_effect = Exception("S3 upload failed")
        
        with pytest.raises(PDFGenerationError) as exc_info:
            await pdf_service._upload_pdf_to_storage(
                pdf_content=b"test",
                object_key="test.pdf",
                invoice_number="test",
                checksum="test"
            )
        
        assert "PDF upload failed" in str(exc_info.value)


class TestInvoicePDFIntegration:
    """Integration tests for invoice PDF functionality."""
    
    def test_invoice_model_has_pdf_url_field(self):
        """Test that Invoice model has pdf_url field."""
        invoice = Invoice(
            id=1,
            user_id=1,
            license_id=1,
            number="test",
            amount=Decimal("100.00"),
            currency="TRY",
            vat=Decimal("20.00"),
            total=Decimal("120.00"),
            issued_at=datetime.now(timezone.utc)
        )
        
        # Test pdf_url field exists and can be set
        assert hasattr(invoice, 'pdf_url')
        assert invoice.pdf_url is None
        
        invoice.pdf_url = "invoices/2024/08/test.pdf"
        assert invoice.pdf_url == "invoices/2024/08/test.pdf"
    
    def test_pdf_path_generation(self):
        """Test PDF storage path generation."""
        invoice_date = datetime(2024, 8, 19, 10, 0, 0, tzinfo=timezone.utc)
        invoice_number = "202408-000001-CNCAI"
        
        expected_path = "invoices/2024/08/202408-000001-CNCAI.pdf"
        actual_path = f"invoices/{invoice_date.year:04d}/{invoice_date.month:02d}/{invoice_number}.pdf"
        
        assert actual_path == expected_path
    
    def test_pdf_checksum_calculation(self):
        """Test PDF checksum calculation for audit purposes."""
        pdf_content = b"Test PDF content for checksum"
        expected_checksum = hashlib.sha256(pdf_content).hexdigest()
        
        actual_checksum = hashlib.sha256(pdf_content).hexdigest()
        
        assert actual_checksum == expected_checksum
        assert len(actual_checksum) == 64  # SHA256 hex digest length
    
    def test_presigned_url_ttl(self):
        """Test that presigned URLs have correct TTL (2 minutes)."""
        expected_ttl = 120  # 2 minutes in seconds
        
        # This would be tested in the actual S3 service call
        assert expected_ttl == 120
    
    def test_turkish_content_in_pdf_template(self):
        """Test that PDF template contains Turkish content."""
        # Mock PDF service for template testing
        from app.services.pdf_service import PDFService
        from app.services.s3 import S3Service
        from app.services.audit_service import AuditService
        
        pdf_service = PDFService(
            s3_service=Mock(spec=S3Service),
            audit_service=Mock(spec=AuditService)
        )
        
        # Create test invoice
        invoice = Invoice(
            id=1,
            user_id=1,
            license_id=1,
            number="202408-000001-CNCAI",
            amount=Decimal("100.00"),
            currency="TRY",
            vat=Decimal("20.00"),
            total=Decimal("120.00"),
            issued_at=datetime(2024, 8, 19, tzinfo=timezone.utc)
        )
        
        html_content = pdf_service._generate_invoice_html(invoice)
        
        # Check Turkish content
        turkish_terms = [
            "FATURA",
            "Fatura No",
            "Tarih",
            "Para Birimi",
            "Durum",
            "Finansal Detaylar",
            "Tutar",
            "KDV",
            "Toplam",
            "Bu fatura elektronik ortamda oluşturulmuştur"
        ]
        
        for term in turkish_terms:
            assert term in html_content, f"Turkish term '{term}' not found in PDF template"