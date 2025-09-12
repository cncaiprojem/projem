"""
Workflow Automation Service for Complex CAD/CAM Processing Pipelines

This service provides workflow automation capabilities including:
- Step-by-step workflow execution
- Conditional branching and decision logic
- Parallel step execution
- Error recovery and compensation
- Workflow templates and reusability
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from celery import Task
from sqlalchemy.orm import Session

from ..core.celery_app import celery_app
from ..core.logging import get_logger
from ..core.metrics import job_progress_gauge
from ..core.telemetry import create_span
from ..models.batch_processing import (
    BatchJob,
    BatchJobStatus,
    WorkflowExecution,
    WorkflowStepStatus,
)
from ..models.user import User
from .batch_operations import BatchOperationsService

logger = get_logger(__name__)


class WorkflowStepType(str, Enum):
    """Types of workflow steps."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    SUBPROCESS = "subprocess"
    MANUAL_APPROVAL = "manual_approval"


class WorkflowConditionOperator(str, Enum):
    """Operators for workflow conditions."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    CONTAINS = "contains"
    IN = "in"
    REGEX_MATCH = "regex_match"


class WorkflowStep:
    """Represents a single step in a workflow."""
    
    def __init__(
        self,
        name: str,
        step_type: WorkflowStepType,
        action: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        condition: Optional[Dict[str, Any]] = None,
        on_success: Optional[str] = None,
        on_failure: Optional[str] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None
    ):
        self.name = name
        self.step_type = step_type
        self.action = action
        self.parameters = parameters or {}
        self.condition = condition
        self.on_success = on_success
        self.on_failure = on_failure
        self.retry_config = retry_config or {"max_retries": 3, "delay": 60}
        self.timeout_seconds = timeout_seconds or 3600
        self.status = WorkflowStepStatus.PENDING
        self.result = None
        self.error = None
        self.start_time = None
        self.end_time = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary representation."""
        return {
            "name": self.name,
            "type": self.step_type,
            "action": self.action,
            "parameters": self.parameters,
            "condition": self.condition,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None
        }


class WorkflowTemplate:
    """Template for reusable workflows."""
    
    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        steps: List[WorkflowStep],
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.version = version
        self.description = description
        self.steps = steps
        self.parameters = parameters or {}
        self.metadata = metadata or {}
    
    def instantiate(self, parameters: Dict[str, Any]) -> List[WorkflowStep]:
        """Create workflow instance from template with given parameters."""
        # Merge template parameters with instance parameters
        merged_params = {**self.parameters, **parameters}
        
        # Create deep copy of steps with parameter substitution
        instantiated_steps = []
        for step in self.steps:
            new_step = WorkflowStep(
                name=step.name,
                step_type=step.step_type,
                action=step.action,
                parameters=self._substitute_parameters(step.parameters, merged_params),
                condition=step.condition,
                on_success=step.on_success,
                on_failure=step.on_failure,
                retry_config=step.retry_config,
                timeout_seconds=step.timeout_seconds
            )
            instantiated_steps.append(new_step)
        
        return instantiated_steps
    
    def _substitute_parameters(
        self,
        obj: Any,
        parameters: Dict[str, Any]
    ) -> Any:
        """Recursively substitute template parameters."""
        if isinstance(obj, str):
            # Check for parameter placeholder
            if obj.startswith("${") and obj.endswith("}"):
                param_name = obj[2:-1]
                return parameters.get(param_name, obj)
            return obj
        elif isinstance(obj, dict):
            return {
                key: self._substitute_parameters(value, parameters)
                for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [
                self._substitute_parameters(item, parameters)
                for item in obj
            ]
        else:
            return obj


class WorkflowAutomation:
    """Service for executing automated workflows."""
    
    def __init__(self, db: Session):
        self.db = db
        self.batch_operations = BatchOperationsService(db)
        self.templates: Dict[str, WorkflowTemplate] = {}
        self._load_default_templates()
    
    def _load_default_templates(self):
        """Load default workflow templates."""
        # Quality assurance workflow
        qa_workflow = WorkflowTemplate(
            name="quality_assurance",
            version="1.0",
            description="Complete quality assurance workflow for CAD models",
            steps=[
                WorkflowStep(
                    name="geometry_check",
                    step_type=WorkflowStepType.SEQUENTIAL,
                    action="quality_check",
                    parameters={"check_type": "geometry_validation"}
                ),
                WorkflowStep(
                    name="topology_check",
                    step_type=WorkflowStepType.SEQUENTIAL,
                    action="quality_check",
                    parameters={"check_type": "topology_check"}
                ),
                WorkflowStep(
                    name="auto_fix",
                    step_type=WorkflowStepType.CONDITIONAL,
                    action="auto_fix_issues",
                    condition={"field": "has_fixable_issues", "operator": "equals", "value": True}
                ),
                WorkflowStep(
                    name="final_validation",
                    step_type=WorkflowStepType.SEQUENTIAL,
                    action="quality_check",
                    parameters={"check_type": "comprehensive"}
                )
            ]
        )
        self.templates["quality_assurance"] = qa_workflow
        
        # Model optimization workflow
        optimization_workflow = WorkflowTemplate(
            name="model_optimization",
            version="1.0",
            description="Optimize CAD models for performance",
            steps=[
                WorkflowStep(
                    name="analyze_complexity",
                    step_type=WorkflowStepType.SEQUENTIAL,
                    action="analyze_model",
                    parameters={"analysis_type": "complexity"}
                ),
                WorkflowStep(
                    name="optimize_steps",
                    step_type=WorkflowStepType.PARALLEL,
                    action="parallel_optimization",
                    parameters={
                        "steps": [
                            {"action": "mesh_optimization", "config": {"decimate": True}},
                            {"action": "feature_cleanup", "config": {"remove_small_features": True}},
                            {"action": "compress_model", "config": {"defeature": True}}
                        ]
                    }
                ),
                WorkflowStep(
                    name="validate_optimization",
                    step_type=WorkflowStepType.SEQUENTIAL,
                    action="validate_model",
                    parameters={"validation_type": "post_optimization"}
                )
            ]
        )
        self.templates["model_optimization"] = optimization_workflow
    
    async def execute_workflow(
        self,
        workflow_execution: WorkflowExecution,
        batch_job: BatchJob,
        user: User,
        template_name: Optional[str] = None,
        custom_steps: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Execute a workflow either from template or custom steps."""
        with create_span("workflow_execution", {"workflow_id": workflow_execution.id}):
            try:
                # Initialize workflow
                workflow_execution.status = WorkflowStepStatus.RUNNING
                workflow_execution.start_time = datetime.now(timezone.utc)
                self.db.commit()
                
                # Get workflow steps
                if template_name:
                    template = self.templates.get(template_name)
                    if not template:
                        raise ValueError(f"Workflow template '{template_name}' not found")
                    steps = template.instantiate(workflow_execution.parameters)
                elif custom_steps:
                    steps = self._parse_custom_steps(custom_steps)
                else:
                    raise ValueError("Either template_name or custom_steps must be provided")
                
                # Update total steps
                workflow_execution.total_steps = len(steps)
                self.db.commit()
                
                # Execute workflow steps
                context = {
                    "batch_job": batch_job,
                    "user": user,
                    "results": {},
                    "variables": workflow_execution.parameters.copy()
                }
                
                for i, step in enumerate(steps):
                    # Update current step
                    workflow_execution.current_step = step.name
                    self.db.commit()
                    
                    # Check if step should be executed
                    if not self._should_execute_step(step, context):
                        step.status = WorkflowStepStatus.SKIPPED
                        workflow_execution.steps.append(step.to_dict())
                        continue
                    
                    # Execute step
                    try:
                        result = await self._execute_step(step, context)
                        
                        # Update context with result
                        context["results"][step.name] = result
                        context["last_result"] = result
                        
                        # Update step status
                        step.status = WorkflowStepStatus.COMPLETED
                        step.result = result
                        
                        # Update workflow execution
                        workflow_execution.completed_steps += 1
                        workflow_execution.step_results[step.name] = result
                        
                        # Handle success action
                        if step.on_success:
                            await self._handle_step_action(step.on_success, context)
                        
                    except Exception as e:
                        logger.error(f"Workflow step '{step.name}' failed: {str(e)}")
                        
                        # Update step status
                        step.status = WorkflowStepStatus.FAILED
                        step.error = str(e)
                        
                        # Update workflow execution
                        workflow_execution.failed_steps += 1
                        workflow_execution.error_step = step.name
                        workflow_execution.error_message = str(e)
                        
                        # Handle failure action
                        if step.on_failure:
                            await self._handle_step_action(step.on_failure, context)
                        
                        # Check if workflow should continue
                        if not step.on_failure or step.on_failure == "fail_workflow":
                            raise
                    
                    finally:
                        # Save step to workflow execution
                        workflow_execution.steps.append(step.to_dict())
                        self.db.commit()
                        
                        # Update progress gauge
                        job_progress_gauge.labels(
                            job_type="workflow",
                            job_id=str(workflow_execution.id)
                        ).set(workflow_execution.progress_percentage)
                
                # Workflow completed successfully
                workflow_execution.status = WorkflowStepStatus.COMPLETED
                workflow_execution.end_time = datetime.now(timezone.utc)
                self.db.commit()
                
                return {
                    "status": "completed",
                    "workflow_id": workflow_execution.id,
                    "completed_steps": workflow_execution.completed_steps,
                    "failed_steps": workflow_execution.failed_steps,
                    "results": context["results"]
                }
                
            except Exception as e:
                logger.error(f"Workflow execution {workflow_execution.id} failed: {str(e)}")
                
                # Update workflow status
                workflow_execution.status = WorkflowStepStatus.FAILED
                workflow_execution.end_time = datetime.now(timezone.utc)
                workflow_execution.error_message = str(e)
                self.db.commit()
                
                raise
    
    def _parse_custom_steps(self, custom_steps: List[Dict[str, Any]]) -> List[WorkflowStep]:
        """Parse custom workflow steps from dictionary format."""
        steps = []
        for step_dict in custom_steps:
            step = WorkflowStep(
                name=step_dict["name"],
                step_type=WorkflowStepType(step_dict.get("type", "sequential")),
                action=step_dict.get("action"),
                parameters=step_dict.get("parameters", {}),
                condition=step_dict.get("condition"),
                on_success=step_dict.get("on_success"),
                on_failure=step_dict.get("on_failure"),
                retry_config=step_dict.get("retry_config"),
                timeout_seconds=step_dict.get("timeout", 3600)
            )
            steps.append(step)
        return steps
    
    def _should_execute_step(self, step: WorkflowStep, context: Dict[str, Any]) -> bool:
        """Check if a step should be executed based on conditions."""
        if not step.condition:
            return True
        
        condition = step.condition
        field_value = self._get_field_value(condition["field"], context)
        operator = WorkflowConditionOperator(condition["operator"])
        compare_value = condition["value"]
        
        if operator == WorkflowConditionOperator.EQUALS:
            return field_value == compare_value
        elif operator == WorkflowConditionOperator.NOT_EQUALS:
            return field_value != compare_value
        elif operator == WorkflowConditionOperator.GREATER_THAN:
            return field_value > compare_value
        elif operator == WorkflowConditionOperator.LESS_THAN:
            return field_value < compare_value
        elif operator == WorkflowConditionOperator.CONTAINS:
            return compare_value in field_value
        elif operator == WorkflowConditionOperator.IN:
            return field_value in compare_value
        elif operator == WorkflowConditionOperator.REGEX_MATCH:
            import re
            return bool(re.match(compare_value, str(field_value)))
        
        return False
    
    def _get_field_value(self, field_path: str, context: Dict[str, Any]) -> Any:
        """Get field value from context using dot notation."""
        parts = field_path.split(".")
        value = context
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        
        return value
    
    async def _execute_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single workflow step."""
        step.start_time = datetime.now(timezone.utc)
        
        try:
            if step.step_type == WorkflowStepType.SEQUENTIAL:
                result = await self._execute_sequential_step(step, context)
            elif step.step_type == WorkflowStepType.PARALLEL:
                result = await self._execute_parallel_step(step, context)
            elif step.step_type == WorkflowStepType.CONDITIONAL:
                result = await self._execute_conditional_step(step, context)
            elif step.step_type == WorkflowStepType.LOOP:
                result = await self._execute_loop_step(step, context)
            elif step.step_type == WorkflowStepType.SUBPROCESS:
                result = await self._execute_subprocess_step(step, context)
            elif step.step_type == WorkflowStepType.MANUAL_APPROVAL:
                result = await self._execute_manual_approval_step(step, context)
            else:
                raise ValueError(f"Unknown step type: {step.step_type}")
            
            step.end_time = datetime.now(timezone.utc)
            return result
            
        except Exception as e:
            step.end_time = datetime.now(timezone.utc)
            raise
    
    async def _execute_sequential_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a sequential workflow step."""
        # Map action to actual implementation
        if step.action == "quality_check":
            return await self._execute_quality_check(step, context)
        elif step.action == "mesh_optimization":
            return await self._execute_mesh_optimization(step, context)
        elif step.action == "analyze_model":
            return await self._execute_model_analysis(step, context)
        elif step.action == "validate_model":
            return await self._execute_model_validation(step, context)
        else:
            # Generic action execution
            return {"action": step.action, "status": "completed", "parameters": step.parameters}
    
    async def _execute_parallel_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute multiple actions in parallel."""
        parallel_steps = step.parameters.get("steps", [])
        parallel_limit = step.parameters.get("parallel_limit", 5)
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(parallel_limit)
        
        async def execute_with_semaphore(sub_step):
            async with semaphore:
                sub_step_obj = WorkflowStep(
                    name=f"{step.name}_{sub_step.get('action')}",
                    step_type=WorkflowStepType.SEQUENTIAL,
                    action=sub_step.get("action"),
                    parameters=sub_step.get("config", {})
                )
                return await self._execute_sequential_step(sub_step_obj, context)
        
        # Use configurable timeout
        timeout = step.parameters.get("timeout", 3600)  # Default 1 hour
        
        # Execute all parallel steps
        results = await asyncio.wait_for(
            asyncio.gather(
                *[execute_with_semaphore(sub_step) for sub_step in parallel_steps],
                return_exceptions=True
            ),
            timeout=timeout
        )
        
        # Process results
        successful = []
        failed = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed.append({
                    "step": parallel_steps[i],
                    "error": str(result)
                })
            else:
                successful.append(result)
        
        return {
            "parallel_execution": True,
            "successful": successful,
            "failed": failed,
            "total": len(parallel_steps)
        }
    
    async def _execute_conditional_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a conditional workflow step."""
        # Condition already checked in _should_execute_step
        # Just execute the action
        return await self._execute_sequential_step(step, context)
    
    async def _execute_loop_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a loop workflow step."""
        items = step.parameters.get("items", [])
        loop_action = step.parameters.get("action")
        results = []
        
        for item in items:
            loop_context = {**context, "loop_item": item}
            loop_step = WorkflowStep(
                name=f"{step.name}_item",
                step_type=WorkflowStepType.SEQUENTIAL,
                action=loop_action,
                parameters={**step.parameters, "item": item}
            )
            result = await self._execute_sequential_step(loop_step, loop_context)
            results.append(result)
        
        return {
            "loop_execution": True,
            "results": results,
            "total_iterations": len(items)
        }
    
    async def _execute_subprocess_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a subprocess (nested workflow)."""
        subprocess_name = step.parameters.get("workflow")
        subprocess_params = step.parameters.get("parameters", {})
        
        # Create sub-workflow execution
        sub_execution = WorkflowExecution(
            batch_job_id=context["batch_job"].id,
            workflow_name=f"{step.name}_subprocess",
            workflow_version="1.0",
            parameters=subprocess_params
        )
        self.db.add(sub_execution)
        self.db.commit()
        
        # Execute sub-workflow
        result = await self.execute_workflow(
            sub_execution,
            context["batch_job"],
            context["user"],
            template_name=subprocess_name
        )
        
        return {
            "subprocess": subprocess_name,
            "execution_id": sub_execution.id,
            "result": result
        }
    
    async def _execute_manual_approval_step(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a manual approval step."""
        # In a real implementation, this would create an approval request
        # and wait for user action
        return {
            "approval_required": True,
            "approver": step.parameters.get("approver"),
            "status": "pending_approval",
            "message": step.parameters.get("message", "Manual approval required")
        }
    
    async def _execute_quality_check(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute quality check action."""
        check_type = step.parameters.get("check_type")
        batch_job = context["batch_job"]
        
        # Execute quality check via batch operations
        result = await self.batch_operations._execute_quality_checks(
            batch_job,
            batch_job.input_models[0],  # Assuming single model for workflow
            {"check_types": [check_type]}
        )
        
        return result
    
    async def _execute_mesh_optimization(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute mesh optimization action."""
        batch_job = context["batch_job"]
        config = step.parameters
        
        # Execute optimization via batch operations
        from ..models.model import Model
        model = self.db.query(Model).filter(
            Model.id == batch_job.input_models[0]
        ).first()
        
        result = await self.batch_operations.optimize_mesh(model, config)
        return result
    
    async def _execute_model_analysis(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute model analysis action."""
        analysis_type = step.parameters.get("analysis_type")
        
        # Placeholder for actual analysis
        return {
            "analysis_type": analysis_type,
            "status": "completed",
            "metrics": {
                "complexity": 75,
                "quality_score": 85,
                "optimization_potential": 30
            }
        }
    
    async def _execute_model_validation(
        self,
        step: WorkflowStep,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute model validation action."""
        validation_type = step.parameters.get("validation_type")
        
        # Placeholder for actual validation
        return {
            "validation_type": validation_type,
            "status": "passed",
            "issues": [],
            "score": 95
        }
    
    async def _handle_step_action(self, action: str, context: Dict[str, Any]):
        """Handle step success/failure actions."""
        if action == "fail_workflow":
            raise Exception("Workflow failed due to step failure")
        elif action == "continue":
            pass  # Continue to next step
        elif action == "retry":
            pass  # Retry logic would be implemented here
        elif action.startswith("goto:"):
            # Jump to specific step (would need workflow graph support)
            target_step = action.split(":")[1]
            logger.info(f"Would jump to step: {target_step}")
        else:
            logger.warning(f"Unknown step action: {action}")


# Celery task for async workflow execution
@celery_app.task(name="execute_workflow_async", bind=True)
def execute_workflow_async(
    self: Task,
    workflow_execution_id: int,
    batch_job_id: int,
    user_id: int,
    template_name: Optional[str] = None,
    custom_steps: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Celery task to execute a workflow asynchronously."""
    from ..core.database import SessionLocal
    from ..crud.user import get_user_by_id
    
    with SessionLocal() as db:
        try:
            # Get workflow execution
            workflow_execution = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == workflow_execution_id
            ).first()
            if not workflow_execution:
                raise ValueError(f"Workflow execution {workflow_execution_id} not found")
            
            # Get batch job
            batch_job = db.query(BatchJob).filter(
                BatchJob.id == batch_job_id
            ).first()
            if not batch_job:
                raise ValueError(f"Batch job {batch_job_id} not found")
            
            # Get user
            user = get_user_by_id(db, user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Create automation service and execute
            automation = WorkflowAutomation(db)
            
            # Run async function in sync context
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    automation.execute_workflow(
                        workflow_execution,
                        batch_job,
                        user,
                        template_name=template_name,
                        custom_steps=custom_steps
                    )
                )
                return result
            finally:
                loop.close()
            
        except Exception as e:
            logger.error(f"Workflow execution {workflow_execution_id} failed: {str(e)}")
            
            # Update workflow status
            if workflow_execution:
                workflow_execution.status = WorkflowStepStatus.FAILED
                workflow_execution.end_time = datetime.now(timezone.utc)
                workflow_execution.error_message = str(e)
                db.commit()
            
            # Re-raise for Celery retry mechanism
            raise self.retry(exc=e, countdown=60, max_retries=3)