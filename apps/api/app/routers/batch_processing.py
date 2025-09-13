"""
Batch Processing Router for Task 7.23

Provides API endpoints for batch processing and automation.
Routes are registered at /api/v2/batch
"""

from fastapi import APIRouter

# Import the v2 batch processing router
from ..api.v2.batch_processing import router as batch_processing_v2_router

# Re-export the router with the correct prefix
router = APIRouter(
    prefix="/api/v2",
    tags=["batch-processing"],
)

# Include the batch processing routes
router.include_router(batch_processing_v2_router)