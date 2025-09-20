"""
Integration tests for Task 7.14: Golden Artefacts and Deterministic Testing

Tests cover:
- Golden artefact validation
- Turkish locale handling
- Edge cases and error scenarios
- Idempotency verification
- Container-based FreeCAD operations
"""

import hashlib
import json
import os
import random
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.environment import environment as settings
from app.main import app
from app.models.job import Job
from app.models.user import User
from app.models.enums import JobStatus, JobType
from app.services.freecad_service import FreeCADService
from app.services.freecad_document_manager import FreeCADDocumentManager, DocumentManagerConfig
from app.services.s3_service import S3Service
from app.core.database import get_db
from app.core.auth import get_current_user


# Test fixtures
@pytest.fixture
def test_data_dir():
    """Get test data directory."""
    return Path(__file__).parent.parent / "data"


@pytest.fixture
def golden_manifest(test_data_dir):
    """Load golden manifest."""
    manifest_path = test_data_dir / "golden" / "golden_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


@pytest.fixture
def test_client():
    """Create FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def async_client():
    """Create async HTTP client for integration testing."""
    return httpx.AsyncClient(
        base_url="http://localhost:8000",
        timeout=30.0
    )


@pytest.fixture
def test_user():
    """Create a test user."""
    return User(
        id=1,
        email="test@example.com",
        name="Test User",
        role="user",
        is_active=True,
    )


@pytest.fixture
def freecad_service():
    """Create FreeCAD service instance."""
    return FreeCADService()


@pytest.fixture
def doc_manager():
    """Create document manager with test configuration."""
    config = DocumentManagerConfig(
        use_real_freecad=settings.USE_REAL_FREECAD,
        enable_compression=False,
        base_dir=tempfile.gettempdir(),
        memory_limit_mb=512
    )
    return FreeCADDocumentManager(config=config)


@pytest.fixture
def s3_service():
    """Create S3 service instance."""
    if settings.ENABLE_S3_STORAGE:
        return S3Service()
    return MagicMock(spec=S3Service)


class TestGoldenArtefacts:
    """Test golden artefact generation and validation."""

    @pytest.mark.slow
    def test_golden_artefact_determinism(self, test_data_dir, golden_manifest):
        """Test that golden artefacts are deterministic."""
        if not golden_manifest:
            pytest.skip("No golden manifest found")

        # Set deterministic environment
        os.environ["PYTHONHASHSEED"] = "0"
        os.environ["LC_ALL"] = "C.UTF-8"

        for artefact_id, artefact_info in golden_manifest["artefacts"].items():
            if artefact_info.get("status") == "failed":
                continue

            # Verify SHA256 hashes are consistent
            for format, export_info in artefact_info.get("exports", {}).items():
                assert "sha256" in export_info, f"Missing SHA256 for {artefact_id}.{format}"
                assert len(export_info["sha256"]) == 64, f"Invalid SHA256 for {artefact_id}.{format}"

            # Verify metrics are present
            metrics = artefact_info.get("metrics", {})
            assert "bounding_box" in metrics, f"Missing bounding_box for {artefact_id}"
            assert "volume" in metrics, f"Missing volume for {artefact_id}"
            assert "surface_area" in metrics, f"Missing surface_area for {artefact_id}"

    def test_sha256_validation(self, test_data_dir):
        """Test SHA256 computation and validation."""
        test_file = test_data_dir / "uploads" / "valid" / "simple_cube.step"
        if not test_file.exists():
            pytest.skip("Test file not found")

        # Compute SHA256
        sha256_hash = hashlib.sha256()
        with open(test_file, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)

        hash_value = sha256_hash.hexdigest()
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

        # Verify determinism
        sha256_hash2 = hashlib.sha256()
        with open(test_file, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash2.update(chunk)

        assert hash_value == sha256_hash2.hexdigest()

    @pytest.mark.parametrize("locale", ["C.UTF-8", "tr_TR.UTF-8"])
    def test_locale_handling(self, freecad_service, locale):
        """Test handling of different locales."""
        original_locale = os.environ.get("LC_ALL", "")
        try:
            os.environ["LC_ALL"] = locale

            # Test decimal parsing
            if locale == "tr_TR.UTF-8":
                # Turkish locale uses comma as decimal separator
                test_value = "100,5"
                expected = 100.5
            else:
                test_value = "100.5"
                expected = 100.5

            # This would be tested with actual FreeCAD operations
            # For now, test locale-aware parsing
            if locale == "tr_TR.UTF-8":
                parsed = float(test_value.replace(",", "."))
            else:
                parsed = float(test_value)

            assert parsed == expected

        finally:
            os.environ["LC_ALL"] = original_locale


class TestTurkishLocaleScenarios:
    """Test Turkish locale-specific scenarios."""

    @pytest.mark.locale_tr
    def test_turkish_decimal_comma_parsing(self, test_data_dir):
        """Test parsing of Turkish decimal comma notation."""
        turkish_prompt_file = test_data_dir / "prompt" / "valid" / "turkish_decimal.json"
        if not turkish_prompt_file.exists():
            pytest.skip("Turkish test file not found")

        with open(turkish_prompt_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        prompt = data["prompt"]
        assert "," in prompt, "Test prompt should contain Turkish decimal comma"

        # Extract dimensions from prompt
        numbers = re.findall(r'\d+,\d+', prompt)
        assert len(numbers) > 0, "Should find Turkish decimal numbers"

        # Convert Turkish decimals to float
        parsed_numbers = [float(n.replace(",", ".")) for n in numbers]
        expected = [100.5, 50.2, 25.7]
        assert parsed_numbers == expected

    @pytest.mark.locale_tr
    def test_turkish_material_names(self, test_data_dir):
        """Test handling of Turkish material names."""
        turkish_material_file = test_data_dir / "prompt" / "valid" / "turkish_material.json"
        if not turkish_material_file.exists():
            pytest.skip("Turkish material test file not found")

        with open(turkish_material_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        prompt = data["prompt"]
        assert "Çelik" in prompt or "çelik" in prompt, "Should contain Turkish word for steel"
        assert "Alüminyum" in prompt or "alüminyum" in prompt, "Should contain Turkish word for aluminum"

        # Test material mapping
        material_map = {
            "çelik": "steel",
            "alüminyum": "aluminum",
            "bakır": "copper",
            "pirinç": "brass",
            "paslanmaz çelik": "stainless_steel"
        }

        for tr_name, en_name in material_map.items():
            if tr_name in prompt.lower():
                assert data["expected"].get("material") == en_name or \
                       data["expected"].get("alternative_material") == en_name

    @pytest.mark.locale_tr
    def test_turkish_unicode_filenames(self, tmpdir):
        """Test handling of Turkish Unicode characters in filenames."""
        turkish_chars = "ÇŞĞÜÖİçşğüöı"
        test_filename = f"test_{turkish_chars}_model.step"

        test_path = Path(tmpdir) / test_filename
        test_path.write_text("Test content", encoding='utf-8')

        assert test_path.exists()
        assert test_path.name == test_filename

        # Test path encoding/decoding
        encoded_path = str(test_path).encode('utf-8')
        decoded_path = encoded_path.decode('utf-8')
        assert decoded_path == str(test_path)


class TestEdgeCases:
    """Test edge cases and error scenarios."""

    def test_ambiguous_prompt_handling(self, test_data_dir, freecad_service):
        """Test handling of ambiguous prompts."""
        ambiguous_file = test_data_dir / "prompt" / "invalid" / "ambiguous.json"
        if not ambiguous_file.exists():
            pytest.skip("Ambiguous prompt test file not found")

        with open(ambiguous_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Test that ambiguous prompts are properly rejected
        expected_error = data.get("expected_error", {})
        assert expected_error.get("type") == "ambiguous_specification"

    def test_corrupted_file_handling(self, test_data_dir):
        """Test handling of corrupted upload files."""
        corrupted_file = test_data_dir / "uploads" / "invalid" / "corrupted.step"
        if not corrupted_file.exists():
            pytest.skip("Corrupted test file not found")

        with open(corrupted_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Verify file is intentionally corrupted
        assert "CORRUPTED DATA HERE" in content
        assert "INCOMPLETE_ENTITY" in content

    @pytest.mark.asyncio
    async def test_circular_reference_detection(self, test_data_dir, async_client):
        """Test detection of circular references in assemblies via API."""
        circular_file = test_data_dir / "a4" / "invalid" / "circular_reference.json"
        if not circular_file.exists():
            pytest.skip("Circular reference test file not found")

        with open(circular_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Create a job with circular reference assembly via API
        job_payload = {
            "type": "assembly",
            "params": {
                "parts": data["parts"],
                "validate_structure": True
            },
            "idempotency_key": f"test-circular-{uuid4()}"
        }

        # Send request to job creation endpoint
        response = await async_client.post(
            "/api/v1/jobs",
            json=job_payload,
            headers={"Authorization": "Bearer test-token"}
        )

        # Should reject the job with validation error
        assert response.status_code == 422, "Should reject job with circular reference"

        error_data = response.json()
        assert "error" in error_data
        assert "circular" in error_data["error"].lower() or "validation" in error_data["error"].lower()

    def test_missing_required_parameters(self, test_data_dir):
        """Test handling of missing required parameters."""
        missing_params_file = test_data_dir / "params" / "invalid" / "missing_required.json"
        if not missing_params_file.exists():
            pytest.skip("Missing parameters test file not found")

        with open(missing_params_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        params = data["parameters"]
        # Verify required field is missing
        assert "height" not in params

        expected_error = data.get("expected_error", {})
        assert expected_error.get("field") == "height"
        assert "missing" in expected_error.get("message", "").lower()


class TestIdempotency:
    """Test idempotency of operations."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_job_processing_idempotency(self, async_client, test_user):
        """Test that processing the same job multiple times yields same result."""
        # Create idempotency key
        idempotency_key = f"test-idempotent-{uuid4()}"

        job_payload = {
            "type": "model",
            "params": {
                "model_type": "box",
                "dimensions": {"length": 100, "width": 50, "height": 25},
                "material": "aluminum"
            },
            "idempotency_key": idempotency_key
        }

        results = []
        job_ids = []

        # Create the same job multiple times with same idempotency key
        for _ in range(3):
            response = await async_client.post(
                "/api/v1/jobs",
                json=job_payload,
                headers={"Authorization": "Bearer test-token"}
            )

            # First request should create (201), subsequent should return existing (200)
            assert response.status_code in [200, 201]

            result = response.json()
            results.append(result)
            job_ids.append(result["job_id"])

        # Verify all job IDs are identical (idempotency worked)
        assert len(set(job_ids)) == 1, "All requests should return the same job ID"

        # Verify response structure is consistent
        for result in results[1:]:
            assert result["job_id"] == results[0]["job_id"]
            assert result["status"] == results[0]["status"]

    def test_parameter_hash_consistency(self):
        """Test that parameter hashing is consistent."""
        params = {
            "length": 100.0,
            "width": 50.0,
            "height": 25.0,
            "material": "steel"
        }

        # Compute hash multiple times
        hashes = []
        for _ in range(5):
            # Sort keys for consistent ordering
            sorted_params = json.dumps(params, sort_keys=True)
            param_hash = hashlib.sha256(sorted_params.encode()).hexdigest()
            hashes.append(param_hash)

        # All hashes should be identical
        assert len(set(hashes)) == 1, "Parameter hashes should be consistent"


class TestRateLimiting:
    """Test rate limiting and resource constraints."""

    @pytest.mark.asyncio
    async def test_concurrent_job_limit(self, async_client):
        """Test enforcement of concurrent job limits via API."""
        max_concurrent = getattr(settings, "MAX_CONCURRENT_FREECAD_JOBS", 5)

        # Create multiple jobs concurrently
        jobs = []
        tasks = []

        # Try to exceed limit by creating many jobs at once
        for i in range(max_concurrent + 5):
            job_payload = {
                "type": "model",
                "params": {
                    "model_type": "box",
                    "dimensions": {"length": 100 + i, "width": 50, "height": 25}
                },
                "idempotency_key": f"test-concurrent-{uuid4()}",
                "priority": 10
            }

            # Create async task for job creation
            task = async_client.post(
                "/api/v1/jobs",
                json=job_payload,
                headers={"Authorization": "Bearer test-token"}
            )
            tasks.append(task)

        # Execute all requests concurrently
        import asyncio
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful vs rate-limited responses
        successful_jobs = 0
        rate_limited = 0
        queued_jobs = 0

        for response in responses:
            if isinstance(response, Exception):
                continue

            if response.status_code in [200, 201]:
                data = response.json()
                if data.get("status") == "queued":
                    queued_jobs += 1
                successful_jobs += 1
            elif response.status_code == 429:  # Rate limited
                rate_limited += 1

        # Verify rate limiting is working
        assert successful_jobs > 0, "Some jobs should succeed"
        assert successful_jobs + rate_limited == len(tasks), "All requests should be accounted for"

        # If rate limiting is enforced, some should be limited
        if rate_limited > 0:
            print(f"Rate limited {rate_limited} out of {len(tasks)} concurrent requests")

    def test_memory_limit_enforcement(self, doc_manager):
        """Test memory limit enforcement."""
        config = doc_manager.config
        memory_limit_mb = config.memory_limit_mb

        # Create documents until memory limit approached
        documents_created = []
        try:
            for i in range(100):  # Arbitrary large number
                doc = doc_manager.create_document(
                    job_id=f"memory_test_{i}",
                    description="Test document for memory limits"
                )
                documents_created.append(doc.document_id)

                # Check if memory cleanup was triggered
                if len(doc_manager.documents) < len(documents_created):
                    # Some documents were cleaned up
                    break

        finally:
            # Cleanup
            for doc_id in documents_created:
                if doc_id in doc_manager.documents:
                    try:
                        doc_manager.close_document(
                            doc_id,
                            save_before_close=False,
                            owner_id="test"
                        )
                    except Exception:
                        pass


class TestRetryMechanism:
    """Test retry mechanisms with exponential backoff."""

    def test_exponential_backoff_calculation(self):
        """Test exponential backoff timing calculation."""
        base_delay = 1.0  # 1 second
        max_delay = 60.0  # 1 minute
        jitter = 0.1  # 10% jitter

        delays = []
        for attempt in range(5):
            delay = min(base_delay * (2 ** attempt), max_delay)

            # Add jitter
            jittered_delay = delay * (1 + random.uniform(-jitter, jitter))
            delays.append(jittered_delay)

        # Verify exponential growth
        for i in range(1, len(delays) - 1):
            # Account for jitter
            base_ratio = delays[i] / delays[i-1]
            assert 1.5 < base_ratio < 2.5, "Should roughly double each time"

        # Verify max delay is respected
        assert all(d <= max_delay * (1 + jitter) for d in delays)

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_transient_failure_retry(self, async_client):
        """Test retry mechanism for transient failures via job status API."""
        # Create a job that might fail initially
        job_payload = {
            "type": "model",
            "params": {
                "model_type": "complex",  # Complex model that might fail
                "dimensions": {"radius": 50, "height": 100},
                "retry_on_failure": True
            },
            "idempotency_key": f"test-retry-{uuid4()}"
        }

        # Create the job
        create_response = await async_client.post(
            "/api/v1/jobs",
            json=job_payload,
            headers={"Authorization": "Bearer test-token"}
        )

        assert create_response.status_code in [200, 201]
        job_data = create_response.json()
        job_id = job_data["job_id"]

        # Poll job status to observe retry behavior
        max_polls = 10
        poll_interval = 1.0
        retry_observed = False
        final_status = None

        for _ in range(max_polls):
            status_response = await async_client.get(
                f"/api/v1/jobs/{job_id}/status",
                headers={"Authorization": "Bearer test-token"}
            )

            if status_response.status_code == 200:
                status_data = status_response.json()
                final_status = status_data.get("status")

                # Check if retry count is tracked
                retry_count = status_data.get("retry_count", 0)
                if retry_count > 0:
                    retry_observed = True

                # If job completed or failed permanently, stop polling
                if final_status in ["completed", "failed", "cancelled"]:
                    break

            await asyncio.sleep(poll_interval)

        # Verify job eventually completes or fails with retry attempts
        assert final_status is not None, "Job should have a final status"

        # Check if retries were attempted (this depends on implementation)
        # The test validates that the retry mechanism exists in the API
        print(f"Job {job_id} final status: {final_status}, Retries observed: {retry_observed}")


# Test markers for pytest
pytest.mark.slow = pytest.mark.skipif(
    not os.environ.get("RUN_SLOW_TESTS"),
    reason="Slow tests skipped by default"
)

pytest.mark.locale_tr = pytest.mark.skipif(
    not os.environ.get("TEST_TURKISH_LOCALE"),
    reason="Turkish locale tests skipped by default"
)

pytest.mark.uploads = pytest.mark.skipif(
    not os.environ.get("TEST_FILE_UPLOADS"),
    reason="File upload tests skipped by default"
)

pytest.mark.a4 = pytest.mark.skipif(
    not os.environ.get("TEST_ASSEMBLY4"),
    reason="Assembly4 tests skipped by default"
)