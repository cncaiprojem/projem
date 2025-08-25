"""
Test PR #281 fixes: params_hash performance optimization and database-agnostic error handling.

This test verifies:
1. params_hash is calculated and stored when creating jobs
2. Idempotency checks use stored hash instead of recalculating
3. Database-agnostic constraint name checking works
"""

import hashlib
import json
import uuid
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models import Job
from app.models.enums import JobStatus, JobType
from app.routers.designs_v1 import (
    handle_idempotency,
    create_job_from_design,
    handle_integrity_error_with_idempotency,
)
from app.routers.contexts import JobRequestContext, JobResponseContext
from app.middleware.jwt_middleware import AuthenticatedUser
from app.schemas.design_v2 import DesignPromptInput


@pytest.fixture
def db_session():
    """Create a test database session."""
    # Use in-memory SQLite for tests
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()


def test_params_hash_is_stored_on_job_creation(db_session: Session):
    """Test that params_hash is calculated and stored when creating a job."""
    
    # Create mock objects
    user = AuthenticatedUser(
        user_id=1,
        email="test@example.com",
        tenant_id="tenant-123"
    )
    
    license = Mock(id=1)
    
    body = DesignPromptInput(
        prompt="Create a 3D box",
        chain_cam=False,
        chain_sim=False,
        priority=1
    )
    
    idempotency_key = str(uuid.uuid4())
    
    # Create job
    job = create_job_from_design(
        db=db_session,
        current_user=user,
        license=license,
        body=body,
        idempotency_key=idempotency_key,
        job_type=JobType.MODEL,
        input_type="prompt"
    )
    
    # Verify params_hash was calculated and stored
    assert job.params_hash is not None
    
    # Calculate expected hash
    expected_hash = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    
    assert job.params_hash == expected_hash


def test_idempotency_uses_stored_hash(db_session: Session):
    """Test that idempotency check uses stored params_hash instead of recalculating."""
    
    user = AuthenticatedUser(user_id=1, email="test@example.com")
    idempotency_key = str(uuid.uuid4())
    params = {"prompt": "Create a box", "size": 100}
    
    # Calculate hash
    params_hash = hashlib.sha256(
        json.dumps(params, sort_keys=True).encode()
    ).hexdigest()
    
    # Create existing job with params_hash
    existing_job = Job(
        idempotency_key=idempotency_key,
        type=JobType.MODEL,
        status=JobStatus.PENDING,
        params=params,
        params_hash=params_hash,  # Store pre-calculated hash
        user_id=user.user_id
    )
    db_session.add(existing_job)
    db_session.commit()
    
    # Mock the params to be None to prove we're using params_hash
    with patch.object(existing_job, 'params', None):
        # This should still work because it uses params_hash
        result = handle_idempotency(
            db=db_session,
            idempotency_key=idempotency_key,
            request_body=params,
            job_type=JobType.MODEL,
            current_user=user
        )
        
        assert result is not None
        assert result.id == existing_job.id


def test_idempotency_fallback_for_old_jobs(db_session: Session):
    """Test that idempotency still works for jobs without params_hash (backward compatibility)."""
    
    user = AuthenticatedUser(user_id=1, email="test@example.com")
    idempotency_key = str(uuid.uuid4())
    params = {"prompt": "Create a box", "size": 100}
    
    # Create existing job WITHOUT params_hash (simulating old job)
    existing_job = Job(
        idempotency_key=idempotency_key,
        type=JobType.MODEL,
        status=JobStatus.PENDING,
        params=params,
        params_hash=None,  # No hash stored
        user_id=user.user_id
    )
    db_session.add(existing_job)
    db_session.commit()
    
    # Should still work by calculating hash from params
    result = handle_idempotency(
        db=db_session,
        idempotency_key=idempotency_key,
        request_body=params,
        job_type=JobType.MODEL,
        current_user=user
    )
    
    assert result is not None
    assert result.id == existing_job.id


def test_database_agnostic_constraint_checking():
    """Test that IntegrityError handling checks constraint name instead of pgcode."""
    
    # Create mock IntegrityError with constraint name
    mock_error = Mock(spec=IntegrityError)
    mock_error.orig = Mock()
    mock_error.orig.__str__ = Mock(return_value="duplicate key value violates unique constraint \"uq_jobs_idempotency_key\"")
    
    # Create mock contexts
    request_context = Mock(spec=JobRequestContext)
    request_context.db = Mock()
    request_context.idempotency_key = "test-key"
    request_context.current_user = Mock(user_id=1)
    request_context.body = Mock()
    request_context.body.model_dump = Mock(return_value={})
    request_context.job_type = JobType.MODEL
    
    response_context = Mock(spec=JobResponseContext)
    response_context.response = Mock()
    response_context.estimated_duration = 120
    
    # Mock handle_idempotency to return an existing job
    with patch('app.routers.designs_v1.handle_idempotency') as mock_handle:
        mock_job = Mock(spec=Job)
        mock_job.id = 123
        mock_job.created_at = Mock()
        mock_job.type = JobType.MODEL
        mock_job.metadata = {"request_id": "req_123"}
        mock_handle.return_value = mock_job
        
        # This should detect the constraint name and handle it properly
        result = handle_integrity_error_with_idempotency(
            mock_error,
            request_context,
            response_context
        )
        
        # Verify it handled the error as an idempotency conflict
        assert result is not None
        assert mock_handle.called
        request_context.db.rollback.assert_called_once()


def test_database_agnostic_constraint_mysql_format():
    """Test that constraint checking works with MySQL-style error messages."""
    
    # Create mock IntegrityError with MySQL-style message
    mock_error = Mock(spec=IntegrityError)
    mock_error.orig = Mock()
    mock_error.orig.__str__ = Mock(return_value="Duplicate entry 'abc-123' for key 'uq_jobs_idempotency_key'")
    
    # Create mock contexts
    request_context = Mock(spec=JobRequestContext)
    request_context.db = Mock()
    request_context.idempotency_key = "abc-123"
    request_context.current_user = Mock(user_id=1)
    request_context.body = Mock()
    request_context.body.model_dump = Mock(return_value={})
    request_context.job_type = JobType.MODEL
    
    response_context = Mock(spec=JobResponseContext)
    
    # Mock handle_idempotency to return an existing job
    with patch('app.routers.designs_v1.handle_idempotency') as mock_handle:
        mock_job = Mock(spec=Job)
        mock_handle.return_value = mock_job
        
        # This should detect the constraint name in MySQL format
        result = handle_integrity_error_with_idempotency(
            mock_error,
            request_context,
            response_context
        )
        
        # Verify it handled the error as an idempotency conflict
        assert result is not None
        assert mock_handle.called


def test_non_idempotency_integrity_error():
    """Test that non-idempotency IntegrityErrors are handled differently."""
    
    # Create mock IntegrityError with different constraint
    mock_error = Mock(spec=IntegrityError)
    mock_error.orig = Mock()
    mock_error.orig.__str__ = Mock(return_value="duplicate key value violates unique constraint \"uq_users_email\"")
    
    # Create mock contexts
    request_context = Mock(spec=JobRequestContext)
    request_context.db = Mock()
    
    response_context = Mock(spec=JobResponseContext)
    
    # This should NOT be handled as idempotency conflict
    with pytest.raises(Exception):  # Should raise HTTPException
        handle_integrity_error_with_idempotency(
            mock_error,
            request_context,
            response_context
        )
    
    # Verify rollback was still called
    request_context.db.rollback.assert_called_once()