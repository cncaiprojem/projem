"""
Tests for AI Adapter Service (Task 7.2)

Tests:
- Turkish prompt processing
- PII masking
- Retry logic and circuit breaker
- Rate limiting
- FreeCAD script generation
- Security validation
"""

import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_adapter import (
    AIAdapter,
    AIAdapterConfig,
    AIProvider,
    AIErrorCode,
    AIException,
    CircuitBreaker,
    CircuitBreakerState,
    RateLimiter,
    FreeCADScriptResponse,
    TURKISH_CAD_GLOSSARY
)
from app.services.freecad import (
    FreeCADScriptGenerator,
    GeometryValidator,
    StandardPartsLibrary,
    ScriptTemplate
)
from app.models.ai_suggestions import AISuggestion


@pytest.fixture
def mock_config():
    """Mock AI adapter configuration."""
    return AIAdapterConfig(
        provider=AIProvider.OPENAI,
        api_key="test-key-123",
        model="gpt-4",
        max_tokens=1000,
        timeout=5,
        temperature=0.3
    )


@pytest.fixture
def ai_adapter(mock_config):
    """Create AI adapter with mocked client."""
    adapter = AIAdapter(config=mock_config)
    adapter._client = MagicMock()
    return adapter


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response."""
    return {
        "content": json.dumps({
            "language": "tr",
            "units": "mm",
            "intent": "freecad_script",
            "glossary_used": True,
            "parameters": {
                "outer_diameter": 20.0,
                "hole_diameter": 8.5,
                "thickness": 5.0
            },
            "script_py": """import FreeCAD as App
import Part

doc = App.newDocument("flange")
outer_d = 20.0
thickness = 5.0
hole_d = 8.5

body = Part.makeCylinder(outer_d/2.0, thickness)
hole = Part.makeCylinder(hole_d/2.0, thickness)
result = body.cut(hole)

Part.show(result)
doc.recompute()""",
            "warnings": ["Varsayılan kalınlık 5mm kullanıldı"],
            "requires_clarification": False
        }, ensure_ascii=False),
        "usage": {
            "prompt_tokens": 250,
            "completion_tokens": 150
        }
    }


class TestTurkishGlossary:
    """Test Turkish CAD glossary translation."""
    
    def test_glossary_contains_common_terms(self):
        """Test that glossary contains common Turkish CAD terms."""
        assert "vida" in TURKISH_CAD_GLOSSARY
        assert "flanş" in TURKISH_CAD_GLOSSARY
        assert "mil" in TURKISH_CAD_GLOSSARY
        assert "yatak" in TURKISH_CAD_GLOSSARY
        assert "dişli" in TURKISH_CAD_GLOSSARY
        
        assert TURKISH_CAD_GLOSSARY["vida"] == "screw"
        assert TURKISH_CAD_GLOSSARY["flanş"] == "flange"
    
    def test_apply_glossary(self, ai_adapter):
        """Test glossary application to prompts."""
        prompt = "M8 vida deliği olan 20mm flanş yapın"
        enhanced, used = ai_adapter._apply_glossary(prompt)
        
        assert used is True
        assert "vida=screw" in enhanced
        assert "flanş=flange" in enhanced


class TestPIIMasking:
    """Test PII masking for KVKK compliance."""
    
    def test_mask_email_addresses(self):
        """Test email masking."""
        ai_suggestion = AISuggestion(
            request_id="test-123",
            prompt="",
            response={},
            user_id=1
        )
        
        text = "Contact john.doe@example.com for details"
        masked = ai_suggestion.mask_pii(text)
        
        assert "john.doe@example.com" not in masked
        assert "j***e@example.com" in masked
    
    def test_mask_turkish_phone_numbers(self):
        """Test Turkish phone number masking."""
        ai_suggestion = AISuggestion(
            request_id="test-124",
            prompt="",
            response={},
            user_id=1
        )
        
        text = "Call +90 532 123 45 67 or 0532 123 45 67"
        masked = ai_suggestion.mask_pii(text)
        
        assert "532 123 45 67" not in masked
        assert "***-***-****" in masked
    
    def test_mask_turkish_names(self):
        """Test Turkish name masking."""
        ai_suggestion = AISuggestion(
            request_id="test-125",
            prompt="",
            response={},
            user_id=1
        )
        
        text = "Mehmet Yılmaz tarafından tasarlandı"
        masked = ai_suggestion.mask_pii(text)
        
        assert "Mehmet" in masked  # First letter preserved
        assert "Yılmaz" not in masked
        assert "M*** ***" in masked


@pytest.mark.asyncio
class TestAISuggestion:
    """Test AI suggestion generation."""
    
    async def test_successful_suggestion(self, ai_adapter, mock_openai_response):
        """Test successful AI suggestion generation."""
        ai_adapter._client.chat.completions.create = MagicMock(
            return_value=MagicMock(
                choices=[MagicMock(message=MagicMock(content=mock_openai_response["content"]))],
                usage=MagicMock(
                    prompt_tokens=250,
                    completion_tokens=150
                )
            )
        )
        
        response = await ai_adapter.suggest_params(
            prompt="M8 vida deliği olan 20mm flanş",
            user_id="test-user"
        )
        
        assert isinstance(response, FreeCADScriptResponse)
        assert response.language == "tr"
        assert response.units == "mm"
        assert response.script_py is not None
        assert "FreeCAD" in response.script_py
        assert response.parameters["outer_diameter"] == 20.0
    
    async def test_unit_normalization(self, ai_adapter):
        """Test unit conversion to mm."""
        response_data = {
            "language": "tr",
            "units": "cm",
            "parameters": {"length": 10, "width": 5},
            "script_py": "test script",
            "warnings": []
        }
        
        ai_adapter._client.chat.completions.create = MagicMock(
            return_value=MagicMock(
                choices=[MagicMock(message=MagicMock(content=json.dumps(response_data)))],
                usage=MagicMock(prompt_tokens=100, completion_tokens=50)
            )
        )
        
        response = await ai_adapter.suggest_params("test prompt")
        
        assert response.units == "mm"
        assert response.parameters["length"] == 100  # 10cm = 100mm
        assert response.parameters["width"] == 50    # 5cm = 50mm
        assert any("cm → mm" in w for w in response.warnings)
    
    async def test_security_validation(self, ai_adapter):
        """Test script security validation."""
        # Script with forbidden operations
        dangerous_script = """import os
os.system('rm -rf /')
exec('malicious code')"""
        
        response_data = {
            "language": "tr",
            "units": "mm",
            "script_py": dangerous_script,
            "warnings": []
        }
        
        ai_adapter._client.chat.completions.create = MagicMock(
            return_value=MagicMock(
                choices=[MagicMock(message=MagicMock(content=json.dumps(response_data)))],
                usage=MagicMock(prompt_tokens=100, completion_tokens=50)
            )
        )
        
        with pytest.raises(AIException) as exc_info:
            await ai_adapter.suggest_params("test prompt")
        
        assert exc_info.value.error_code == AIErrorCode.SECURITY_VIOLATION
        assert "Forbidden import: os" in str(exc_info.value)


@pytest.mark.asyncio
class TestRetryLogic:
    """Test retry logic with exponential backoff."""
    
    async def test_retry_on_timeout(self, ai_adapter):
        """Test retry on timeout errors."""
        call_count = 0
        
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError()
            return MagicMock(
                choices=[MagicMock(message=MagicMock(content='{"script_py": "test"}'))],
                usage=MagicMock(prompt_tokens=100, completion_tokens=50)
            )
        
        ai_adapter._client.chat.completions.create = MagicMock(side_effect=side_effect)
        
        with patch('asyncio.sleep'):  # Skip actual sleep
            response = await ai_adapter.suggest_params("test", retries=3)
        
        assert call_count == 3
        assert response.script_py == "test"
    
    async def test_all_retries_fail(self, ai_adapter):
        """Test when all retries fail."""
        ai_adapter._client.chat.completions.create = MagicMock(
            side_effect=asyncio.TimeoutError()
        )
        
        with patch('asyncio.sleep'):
            with pytest.raises(AIException) as exc_info:
                await ai_adapter.suggest_params("test", retries=3)
        
        assert exc_info.value.error_code == AIErrorCode.TIMEOUT
        assert "3" in str(exc_info.value)  # Mentions retry count


class TestCircuitBreaker:
    """Test circuit breaker pattern."""
    
    def test_circuit_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        breaker = CircuitBreaker(threshold=3)
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert not breaker.is_open()
        
        # Record failures
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.is_open()
    
    def test_circuit_half_open_after_timeout(self):
        """Test circuit goes to half-open after timeout."""
        breaker = CircuitBreaker(threshold=2, recovery_timeout=1)
        
        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait for recovery timeout
        breaker.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        
        # Should be half-open now
        assert not breaker.is_open()
        assert breaker.state == CircuitBreakerState.HALF_OPEN
    
    def test_circuit_closes_after_success_in_half_open(self):
        """Test circuit closes after success in half-open state."""
        breaker = CircuitBreaker(threshold=2, half_open_requests=1)
        
        # Open circuit
        breaker.record_failure()
        breaker.record_failure()
        
        # Move to half-open
        breaker.state = CircuitBreakerState.HALF_OPEN
        
        # Record success
        breaker.record_success()
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0


class TestRateLimiter:
    """Test rate limiting."""
    
    def test_rate_limit_per_user(self):
        """Test per-user rate limiting."""
        limiter = RateLimiter(limit=3)
        
        # First 3 requests should pass
        assert limiter.check_and_update("user1") is True
        assert limiter.check_and_update("user1") is True
        assert limiter.check_and_update("user1") is True
        
        # 4th request should fail
        assert limiter.check_and_update("user1") is False
        
        # Different user should pass
        assert limiter.check_and_update("user2") is True
    
    def test_rate_limit_window_reset(self):
        """Test rate limit window resets after time."""
        limiter = RateLimiter(limit=2)
        now = datetime.now(timezone.utc)
        
        # Add old requests (> 1 minute ago)
        limiter.requests["user1"] = [
            now - timedelta(minutes=2),
            now - timedelta(minutes=2)
        ]
        
        # Should pass as old requests are cleared
        assert limiter.check_and_update("user1") is True
        assert len(limiter.requests["user1"]) == 1  # Only new request


class TestScriptGenerator:
    """Test FreeCAD script generation."""
    
    def test_generate_from_template(self):
        """Test script generation from template."""
        generator = FreeCADScriptGenerator()
        
        result = generator.generate_from_template(
            template=ScriptTemplate.CYLINDER,
            parameters={"radius": 10, "height": 30},
            name="test_cylinder"
        )
        
        assert "makeCylinder(10" in result.script
        assert "30)" in result.script
        assert result.template_used == ScriptTemplate.CYLINDER
        assert result.parameters["radius"] == 10
    
    def test_parse_and_validate_script(self):
        """Test parsing and validation of script."""
        generator = FreeCADScriptGenerator()
        
        script = """import FreeCAD as App
import Part

diameter = 20.0
length = 100.0
shaft = Part.makeCylinder(diameter/2.0, length)"""
        
        result = generator.parse_and_validate(script)
        
        assert result.script is not None
        assert "FreeCAD" in result.imports
        assert "Part" in result.imports
        assert result.parameters["diameter"] == 20.0
        assert result.parameters["length"] == 100.0
    
    def test_security_validation_fails(self):
        """Test security validation rejects dangerous scripts."""
        generator = FreeCADScriptGenerator()
        
        dangerous_script = """import os
os.system('rm -rf /')"""
        
        with pytest.raises(ValueError) as exc_info:
            generator.parse_and_validate(dangerous_script)
        
        assert "Security violations" in str(exc_info.value)
        assert "os" in str(exc_info.value)


class TestGeometryValidator:
    """Test geometry validation."""
    
    def test_mock_validation(self):
        """Test mock validation when FreeCAD not available."""
        validator = GeometryValidator()
        
        # Mock shape object
        mock_shape = MagicMock()
        mock_shape.__dict__ = {
            "volume": 5000.0,
            "area": 1200.0,
            "center_of_mass": [0, 0, 25]
        }
        
        result = validator.validate_shape(mock_shape)
        
        assert result.is_valid
        assert result.volume == 5000.0
        assert result.area == 1200.0
        assert len(result.export_formats) > 0
        assert any("mock validation" in w for w in result.warnings)
    
    def test_manufacturing_constraints(self):
        """Test manufacturing constraints validation."""
        from app.services.freecad import ManufacturingConstraints
        
        constraints = ManufacturingConstraints(
            min_wall_thickness=2.0,
            min_draft_angle=3.0,
            max_aspect_ratio=8.0
        )
        
        # Test thickness validation
        valid, msg = constraints.validate_thickness(3.0)
        assert valid is True
        assert msg is None
        
        invalid, msg = constraints.validate_thickness(1.0)
        assert invalid is False
        assert "below minimum" in msg
        
        # Test draft validation
        valid, msg = constraints.validate_draft(5.0)
        assert valid is True
        
        invalid, msg = constraints.validate_draft(1.0)
        assert invalid is False
        assert "below minimum" in msg


class TestStandardParts:
    """Test standard parts library."""
    
    def test_get_standard_part(self):
        """Test getting standard part definition."""
        library = StandardPartsLibrary()
        
        part = library.get_part("DIN933")
        assert part is not None
        assert part.name == "Hex Head Bolt"
        assert part.standard_type.value == "DIN"
        assert "M8x20" in part.sizes
    
    def test_search_parts(self):
        """Test searching standard parts."""
        library = StandardPartsLibrary()
        
        # Search by category
        from app.services.freecad import PartCategory
        fasteners = library.search_parts(category=PartCategory.FASTENERS)
        assert len(fasteners) > 0
        assert all(p.category == PartCategory.FASTENERS for p in fasteners)
        
        # Search by query
        bolts = library.search_parts(query="bolt")
        assert len(bolts) > 0
        assert any("bolt" in p.name.lower() for p in bolts)
    
    def test_generate_part_script(self):
        """Test generating script for standard part."""
        library = StandardPartsLibrary()
        
        script = library.generate_part_script("DIN933", "M8x20")
        assert script is not None
        assert "diameter = 8" in script
        assert "length = 20" in script
        assert "hex" in script.lower()
    
    def test_resolve_references(self):
        """Test resolving part and template references."""
        library = StandardPartsLibrary()
        
        results = library.resolve_references(
            parts=[{"code": "DIN933", "size": "M8x20"}],
            templates=[{"id": "flange_v3", "s3": "s3://bucket/flange.FCStd"}]
        )
        
        assert len(results["parts"]) == 1
        assert results["parts"][0]["code"] == "DIN933"
        assert "script" in results["parts"][0]
        
        assert len(results["templates"]) == 1
        assert results["templates"][0]["s3"] == "s3://bucket/flange.FCStd"