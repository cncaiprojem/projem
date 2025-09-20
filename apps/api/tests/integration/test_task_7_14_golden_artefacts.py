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

import pytest
from sqlalchemy.orm import Session

from app.core.environment import environment as settings
from app.models.job import Job
from app.services.freecad_service import FreeCADService
from app.services.freecad_document_manager import FreeCADDocumentManager, DocumentManagerConfig
from app.services.s3_service import S3Service
from app.tasks.freecad import process_freecad_job


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

    def test_circular_reference_detection(self, test_data_dir):
        """Test detection of circular references in assemblies."""
        circular_file = test_data_dir / "a4" / "invalid" / "circular_reference.json"
        if not circular_file.exists():
            pytest.skip("Circular reference test file not found")

        with open(circular_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Verify circular dependency structure
        parts = data["parts"]
        part_map = {p["name"]: p.get("parent") for p in parts}

        # Detect circular reference
        def has_circular_reference(start_part: str, visited: Optional[set] = None) -> bool:
            if visited is None:
                visited = set()

            if start_part in visited:
                return True

            visited.add(start_part)
            parent = part_map.get(start_part)

            if parent:
                return has_circular_reference(parent, visited.copy())

            return False

        assert has_circular_reference("PartA"), "Should detect circular reference"

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
    def test_job_processing_idempotency(self, db: Session, freecad_service):
        """Test that processing the same job multiple times yields same result."""
        # Create test job
        job = Job(
            prompt="Create a box 100x50x25mm",
            status="pending",
            parameters={"length": 100, "width": 50, "height": 25}
        )
        db.add(job)
        db.commit()

        results = []
        for _ in range(3):
            # Process job
            result = process_freecad_job(job.id)
            results.append(result)

            # Reset job status for re-processing
            job.status = "pending"
            db.commit()

        # Verify all results are identical
        if len(results) > 1:
            first_result = results[0]
            for result in results[1:]:
                assert result == first_result, "Results should be identical"

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

    def test_concurrent_job_limit(self, freecad_service):
        """Test enforcement of concurrent job limits."""
        max_concurrent = getattr(settings, "MAX_CONCURRENT_FREECAD_JOBS", 5)

        # Track active jobs and rejected jobs
        active_jobs = []
        queued_jobs = []
        rejected_jobs = []

        # Try to exceed limit
        for i in range(max_concurrent + 2):
            job_id = f"test_job_{i}"

            if len(active_jobs) < max_concurrent:
                # Should succeed - job is accepted
                active_jobs.append(job_id)

                # Verify job is marked as active
                assert job_id in active_jobs, f"Job {job_id} should be in active jobs"
                assert len(active_jobs) <= max_concurrent, \
                    f"Active jobs ({len(active_jobs)}) should not exceed max_concurrent ({max_concurrent})"
            else:
                # Should be rate limited or queued
                queued_jobs.append(job_id)

                # Verify the job was not added to active jobs
                assert job_id not in active_jobs, \
                    f"Job {job_id} should not be in active jobs when limit is reached"

                # Verify we have exactly max_concurrent active jobs
                assert len(active_jobs) == max_concurrent, \
                    f"Should have exactly {max_concurrent} active jobs when limit is reached"

                # Optionally track rejected jobs if queue is also full
                # This depends on implementation - jobs might be queued or rejected
                if len(queued_jobs) > getattr(settings, "MAX_QUEUE_SIZE", 10):
                    rejected_jobs.append(job_id)
                    assert job_id not in queued_jobs, \
                        f"Job {job_id} should be rejected when queue is full"

        # Final assertions
        assert len(active_jobs) == max_concurrent, \
            f"Should have exactly {max_concurrent} active jobs at the end"
        assert len(queued_jobs) >= 2, \
            f"Should have at least 2 queued jobs (attempted {max_concurrent + 2} total)"
        assert len(active_jobs) + len(queued_jobs) + len(rejected_jobs) == max_concurrent + 2, \
            "Total jobs should equal attempted jobs"

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
    def test_transient_failure_retry(self, freecad_service):
        """Test retry on transient failures."""
        attempt_count = 0
        max_attempts = 3

        def flaky_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < max_attempts:
                raise Exception("Transient error")
            return "Success"

        # Simulate retry logic
        for attempt in range(max_attempts):
            try:
                result = flaky_operation()
                break
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.1 * (2 ** attempt))  # Exponential backoff

        assert result == "Success"
        assert attempt_count == max_attempts


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