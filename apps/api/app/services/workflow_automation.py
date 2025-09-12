"""
Workflow Automation System for Task 7.23

Provides DAG-based workflow automation with:
- Workflow definition and validation
- Step execution with conditions
- Branching and parallel execution
- Error handling and recovery
- State management and persistence
"""

from __future__ import annotations

import ast
import asyncio
import json
import operator
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator

from ..core.logging import get_logger
from ..core.metrics import workflow_counter, workflow_duration_histogram
from ..core.telemetry import create_span
from ..models.enums import StepType, StepStatus, WorkflowStatus, ErrorHandling

logger = get_logger(__name__)


class StepCondition(BaseModel):
    """Condition for step execution."""
    field: str = Field(description="Alan adı")
    operator: str = Field(description="Operatör (eq, ne, gt, lt, gte, lte, in, contains)")
    value: Any = Field(description="Karşılaştırma değeri")
    
    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate condition against context."""
        field_value = context.get(self.field)
        
        # Handle None values
        if field_value is None:
            if self.operator == "eq":
                return self.value is None
            elif self.operator == "ne":
                return self.value is not None
            else:
                return False  # Other operations require non-None values
        
        try:
            if self.operator == "eq":
                return field_value == self.value
            elif self.operator == "ne":
                return field_value != self.value
            elif self.operator == "gt":
                return field_value > self.value
            elif self.operator == "lt":
                return field_value < self.value
            elif self.operator == "gte":
                return field_value >= self.value
            elif self.operator == "lte":
                return field_value <= self.value
            elif self.operator == "in":
                return field_value in self.value
            elif self.operator == "contains":
                return self.value in field_value
            else:
                logger.warning(f"Unknown operator: {self.operator}")
                return False
        except TypeError as e:
            # Handle incompatible type comparisons
            logger.debug(f"Type error in condition evaluation: {e}. Field: {self.field}, Operator: {self.operator}, Field value type: {type(field_value)}, Compare value type: {type(self.value)}")
            return False
        except Exception as e:
            # Handle any other unexpected errors
            logger.warning(f"Error evaluating condition: {e}. Field: {self.field}, Operator: {self.operator}")
            return False


class WorkflowStep(BaseModel):
    """Individual workflow step."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="Adım adı")
    type: StepType = Field(default=StepType.ACTION)
    action: Optional[str] = Field(default=None, description="Çalıştırılacak aksiyon")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parametreler")
    conditions: List[StepCondition] = Field(default_factory=list, description="Çalıştırma koşulları")
    dependencies: List[str] = Field(default_factory=list, description="Bağımlı adımlar")
    error_handling: ErrorHandling = Field(default=ErrorHandling.FAIL)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    branches: Optional[Dict[str, List[str]]] = Field(default=None, description="Dal koşulları")
    loop_condition: Optional[StepCondition] = Field(default=None, description="Döngü koşulu")
    parallel_steps: Optional[List[str]] = Field(default=None, description="Paralel adımlar")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "Model İşleme",
            "type": "action",
            "action": "process_model",
            "parameters": {"format": "step"},
            "conditions": [{"field": "model_type", "operator": "eq", "value": "cad"}],
            "dependencies": ["validate_input"],
            "error_handling": "retry",
            "max_retries": 3
        }
    ]}}


class Workflow(BaseModel):
    """Workflow definition."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="İş akışı adı")
    description: Optional[str] = Field(default=None, description="Açıklama")
    version: str = Field(default="1.0.0", description="Versiyon")
    steps: List[WorkflowStep] = Field(description="İş akışı adımları")
    entry_point: Optional[str] = Field(default=None, description="Başlangıç adımı")
    global_timeout: Optional[int] = Field(default=None, ge=60, le=86400, description="Toplam timeout (saniye)")
    on_success: Optional[List[str]] = Field(default=None, description="Başarı durumunda çalıştırılacak adımlar")
    on_failure: Optional[List[str]] = Field(default=None, description="Hata durumunda çalıştırılacak adımlar")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: Optional[datetime] = Field(default=None)
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "workflow_started": "İş akışı başladı",
        "workflow_completed": "İş akışı tamamlandı",
        "workflow_failed": "İş akışı başarısız",
        "step_executing": "Adım yürütülüyor",
        "step_completed": "Adım tamamlandı",
        "step_failed": "Adım başarısız"
    })


class StepResult(BaseModel):
    """Result of step execution."""
    step_id: str = Field(description="Adım ID")
    status: StepStatus = Field(description="Durum")
    output: Optional[Any] = Field(default=None, description="Çıktı")
    error: Optional[str] = Field(default=None, description="Hata mesajı")
    start_time: datetime = Field(description="Başlangıç zamanı")
    end_time: Optional[datetime] = Field(default=None, description="Bitiş zamanı")
    duration_ms: Optional[float] = Field(default=None, description="Süre (ms)")
    retries: int = Field(default=0, description="Tekrar sayısı")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowExecution(BaseModel):
    """Workflow execution instance."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = Field(description="İş akışı ID")
    status: WorkflowStatus = Field(default=WorkflowStatus.CREATED)
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Giriş verileri")
    context: Dict[str, Any] = Field(default_factory=dict, description="Yürütme bağlamı")
    step_results: Dict[str, StepResult] = Field(default_factory=dict, description="Adım sonuçları")
    current_step: Optional[str] = Field(default=None, description="Mevcut adım")
    start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    end_time: Optional[datetime] = Field(default=None)
    duration_ms: Optional[float] = Field(default=None)
    error: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionOptions(BaseModel):
    """Options for workflow execution."""
    async_execution: bool = Field(default=True, description="Asenkron yürütme")
    save_intermediate: bool = Field(default=True, description="Ara sonuçları kaydet")
    parallel_limit: int = Field(default=10, ge=1, le=100, description="Maksimum paralel adım")
    parallel_timeout: Optional[int] = Field(default=None, ge=1, le=3600, description="Paralel adım zaman aşımı (saniye)")
    retry_delay_ms: int = Field(default=1000, ge=100, le=60000, description="Tekrar gecikme süresi")
    checkpoint_enabled: bool = Field(default=True, description="Checkpoint etkin")
    dry_run: bool = Field(default=False, description="Kuru çalıştırma")


class WorkflowValidationError(Exception):
    """Workflow validation error."""
    pass


class StepExecutor:
    """Execute workflow steps."""
    
    def __init__(self):
        """Initialize step executor."""
        self.action_handlers: Dict[str, Callable] = {}
        self.condition_evaluators: Dict[str, Callable] = {}
    
    def register_action(self, name: str, handler: Callable) -> None:
        """Register an action handler."""
        self.action_handlers[name] = handler
    
    def register_condition(self, name: str, evaluator: Callable) -> None:
        """Register a condition evaluator."""
        self.condition_evaluators[name] = evaluator
    
    async def execute(
        self,
        step: WorkflowStep,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        options: ExecutionOptions
    ) -> StepResult:
        """Execute a workflow step."""
        start_time = datetime.now(UTC)
        result = StepResult(
            step_id=step.id,
            status=StepStatus.RUNNING,
            start_time=start_time
        )
        
        try:
            # Check conditions
            if step.conditions:
                for condition in step.conditions:
                    if not condition.evaluate(context):
                        result.status = StepStatus.SKIPPED
                        result.end_time = datetime.now(UTC)
                        result.duration_ms = (result.end_time - start_time).total_seconds() * 1000
                        logger.info(f"Adım atlandı (koşul sağlanmadı): {step.name}")
                        return result
            
            # Execute based on step type
            if step.type == StepType.ACTION:
                output = await self._execute_action(step, input_data, context, options)
            elif step.type == StepType.CONDITION:
                output = await self._evaluate_condition(step, context)
            elif step.type == StepType.BRANCH:
                output = await self._execute_branch(step, context)
            elif step.type == StepType.PARALLEL:
                output = await self._execute_parallel(step, input_data, context, options)
            elif step.type == StepType.LOOP:
                output = await self._execute_loop(step, input_data, context, options)
            elif step.type == StepType.WAIT:
                output = await self._execute_wait(step, context)
            else:
                output = None
            
            result.output = output
            result.status = StepStatus.COMPLETED
            
        except Exception as e:
            logger.error(f"Adım hatası {step.name}: {e}")
            result.error = str(e)
            result.status = StepStatus.FAILED
            
            # Handle error based on strategy
            if step.error_handling == ErrorHandling.RETRY and result.retries < step.max_retries:
                result.retries += 1
                await asyncio.sleep(options.retry_delay_ms / 1000)
                return await self.execute(step, input_data, context, options)
            elif step.error_handling == ErrorHandling.SKIP:
                result.status = StepStatus.SKIPPED
            elif step.error_handling == ErrorHandling.CONTINUE:
                result.status = StepStatus.COMPLETED
        
        finally:
            result.end_time = datetime.now(UTC)
            result.duration_ms = (result.end_time - start_time).total_seconds() * 1000
        
        return result
    
    async def _execute_action(
        self,
        step: WorkflowStep,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        options: ExecutionOptions
    ) -> Any:
        """Execute an action step."""
        if options.dry_run:
            logger.info(f"[DRY RUN] Aksiyon çalıştırılacak: {step.action}")
            return {"dry_run": True, "action": step.action}
        
        handler = self.action_handlers.get(step.action)
        if not handler:
            raise ValueError(f"Aksiyon bulunamadı: {step.action}")
        
        # Merge parameters with context
        params = {**context, **step.parameters, **input_data}
        
        # Execute with timeout
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(params),
                    timeout=step.timeout_seconds
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, handler, params),
                    timeout=step.timeout_seconds
                )
            
            return result
            
        except asyncio.TimeoutError:
            raise TimeoutError(f"Adım zaman aşımına uğradı: {step.name}")
    
    async def _evaluate_condition(self, step: WorkflowStep, context: Dict[str, Any]) -> bool:
        """Evaluate a condition step."""
        if step.conditions:
            return all(cond.evaluate(context) for cond in step.conditions)
        return True
    
    async def _execute_branch(self, step: WorkflowStep, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute branching logic."""
        if not step.branches:
            return {"branch": "default"}
        
        for branch_condition, branch_steps in step.branches.items():
            # Evaluate branch condition
            if branch_condition == "default":
                return {"branch": "default", "steps": branch_steps}
            
            # Parse and evaluate condition
            condition_parts = branch_condition.split(":")
            if len(condition_parts) == 3:
                field, operator, value = condition_parts
                condition = StepCondition(field=field, operator=operator, value=value)
                if condition.evaluate(context):
                    return {"branch": branch_condition, "steps": branch_steps}
        
        return {"branch": "none"}
    
    async def _execute_parallel(
        self,
        step: WorkflowStep,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        options: ExecutionOptions
    ) -> List[Any]:
        """Execute parallel steps."""
        if not step.parallel_steps:
            return []
        
        # Create tasks for parallel execution
        tasks = []
        for parallel_step_id in step.parallel_steps[:options.parallel_limit]:
            # Execute each parallel step as an action
            parallel_task = self._execute_parallel_step(
                parallel_step_id,
                input_data,
                context,
                options
            )
            tasks.append(parallel_task)
        
        # Execute all tasks in parallel and collect results
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle any errors
        processed_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Paralel adım hatası {step.parallel_steps[idx]}: {result}")
                if not options.save_intermediate:
                    raise result
                processed_results.append({
                    "step_id": step.parallel_steps[idx],
                    "error": str(result),
                    "status": "failed"
                })
            else:
                processed_results.append({
                    "step_id": step.parallel_steps[idx],
                    "result": result,
                    "status": "completed"
                })
        
        return processed_results
    
    async def _execute_parallel_step(
        self,
        step_id: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        options: ExecutionOptions
    ) -> Any:
        """Execute a single parallel step."""
        try:
            # If we have a registered action handler for this step
            if step_id in self.action_handlers:
                handler = self.action_handlers[step_id]
                
                # Execute with timeout
                # Use configurable timeout with fallback to calculated default
                parallel_timeout = getattr(options, 'parallel_timeout', None) or (options.parallel_limit * 10)
                
                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(
                        handler({**context, **input_data}),
                        timeout=parallel_timeout
                    )
                else:
                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, handler, {**context, **input_data}),
                        timeout=parallel_timeout
                    )
                
                return result
            else:
                # Default parallel step execution
                await asyncio.sleep(0.1)  # Simulate work
                return {"step_id": step_id, "result": "executed", "context": context.get(step_id, {})}
                
        except asyncio.TimeoutError:
            raise TimeoutError(f"Paralel adım zaman aşımına uğradı: {step_id}")
        except Exception as e:
            logger.error(f"Paralel adım yürütme hatası {step_id}: {e}")
            raise
    
    async def _execute_loop(
        self,
        step: WorkflowStep,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        options: ExecutionOptions
    ) -> List[Any]:
        """Execute loop step."""
        results = []
        iteration = 0
        max_iterations = 1000  # Safety limit
        
        while iteration < max_iterations:
            # Check loop condition
            if step.loop_condition and not step.loop_condition.evaluate(context):
                break
            
            # Execute loop body (would need actual step execution)
            result = await self._execute_action(step, input_data, context, options)
            results.append(result)
            
            # Update context for next iteration
            context["loop_iteration"] = iteration
            iteration += 1
        
        return results
    
    async def _execute_wait(self, step: WorkflowStep, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute wait step."""
        wait_time = step.parameters.get("wait_seconds", 1)
        await asyncio.sleep(wait_time)
        return {"waited": wait_time}


class ConditionEvaluator:
    """Evaluate workflow conditions."""
    
    def evaluate_conditions(
        self,
        conditions: List[StepCondition],
        context: Dict[str, Any]
    ) -> bool:
        """Evaluate multiple conditions."""
        if not conditions:
            return True
        
        return all(cond.evaluate(context) for cond in conditions)
    
    def evaluate_complex_condition(
        self,
        condition_expr: str,
        context: Dict[str, Any]
    ) -> bool:
        """Evaluate complex condition expression using safe AST parsing."""
        # Safe expression parser using AST
        # Format: "field1 > 10 AND field2 == 'value'"
        try:
            # Parse the expression into an AST
            tree = ast.parse(condition_expr, mode='eval')
            
            # Validate that the expression only contains safe operations
            if not self._is_safe_expression(tree):
                logger.error(f"Güvenli olmayan ifade tespit edildi: {condition_expr}")
                return False
            
            # Evaluate the expression safely
            return self._safe_eval(tree.body, context)
            
        except Exception as e:
            logger.error(f"Koşul değerlendirme hatası: {e}")
            return False
    
    def _is_safe_expression(self, node: ast.AST) -> bool:
        """Check if an AST node represents a safe expression."""
        # Define allowed node types for safe evaluation
        safe_nodes = (
            ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp,
            ast.Compare, ast.Name, ast.Load, ast.Constant,
            ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq,
            ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
            ast.In, ast.NotIn, ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.Mod, ast.Pow, ast.FloorDiv
        )
        
        # Check all nodes in the tree
        for node in ast.walk(node):
            if not isinstance(node, safe_nodes):
                return False
        
        return True
    
    def _safe_eval(self, node: ast.AST, context: Dict[str, Any]) -> Any:
        """Safely evaluate an AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        
        elif isinstance(node, ast.Name):
            # Get value from context
            return context.get(node.id)
        
        elif isinstance(node, ast.BoolOp):
            # Handle AND/OR operations
            if isinstance(node.op, ast.And):
                return all(self._safe_eval(value, context) for value in node.values)
            elif isinstance(node.op, ast.Or):
                return any(self._safe_eval(value, context) for value in node.values)
        
        elif isinstance(node, ast.UnaryOp):
            # Handle NOT operation
            if isinstance(node.op, ast.Not):
                return not self._safe_eval(node.operand, context)
        
        elif isinstance(node, ast.Compare):
            # Handle comparison operations
            left = self._safe_eval(node.left, context)
            
            for op, comparator in zip(node.ops, node.comparators):
                right = self._safe_eval(comparator, context)
                
                if isinstance(op, ast.Eq):
                    result = left == right
                elif isinstance(op, ast.NotEq):
                    result = left != right
                elif isinstance(op, ast.Lt):
                    result = left < right
                elif isinstance(op, ast.LtE):
                    result = left <= right
                elif isinstance(op, ast.Gt):
                    result = left > right
                elif isinstance(op, ast.GtE):
                    result = left >= right
                elif isinstance(op, ast.In):
                    result = left in right
                elif isinstance(op, ast.NotIn):
                    result = left not in right
                elif isinstance(op, ast.Is):
                    result = left is right
                elif isinstance(op, ast.IsNot):
                    result = left is not right
                else:
                    return False
                
                if not result:
                    return False
                
                left = right
            
            return True
        
        elif isinstance(node, ast.BinOp):
            # Handle binary operations
            left = self._safe_eval(node.left, context)
            right = self._safe_eval(node.right, context)
            
            ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
            }
            
            op_func = ops.get(type(node.op))
            if op_func:
                return op_func(left, right)
        
        return False


class WorkflowEngine:
    """Main workflow automation engine."""
    
    def __init__(self):
        """Initialize workflow engine."""
        self.workflows: Dict[str, Workflow] = {}
        self.executions: Dict[str, WorkflowExecution] = {}
        self.step_executor = StepExecutor()
        self.condition_evaluator = ConditionEvaluator()
    
    def validate_workflow_dag(self, workflow: Workflow) -> bool:
        """
        Validate workflow DAG for cycles and connectivity.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            True if valid, raises WorkflowValidationError otherwise
        """
        # Build adjacency list
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        step_map = {step.id: step for step in workflow.steps}
        
        for step in workflow.steps:
            for dep_id in step.dependencies:
                if dep_id not in step_map:
                    raise WorkflowValidationError(f"Bağımlılık bulunamadı: {dep_id}")
                graph[dep_id].append(step.id)
                in_degree[step.id] += 1
        
        # Topological sort to detect cycles
        queue = deque([step.id for step in workflow.steps if in_degree[step.id] == 0])
        sorted_count = 0
        
        while queue:
            current = queue.popleft()
            sorted_count += 1
            
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if sorted_count != len(workflow.steps):
            raise WorkflowValidationError("İş akışı döngü içeriyor")
        
        # Check entry point
        if workflow.entry_point and workflow.entry_point not in step_map:
            raise WorkflowValidationError(f"Başlangıç noktası bulunamadı: {workflow.entry_point}")
        
        return True
    
    def topological_sort(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """Sort steps in topological order."""
        # Build adjacency list and in-degree map
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        step_map = {step.id: step for step in steps}
        
        for step in steps:
            for dep_id in step.dependencies:
                if dep_id in step_map:
                    graph[dep_id].append(step.id)
                    in_degree[step.id] += 1
        
        # Find all nodes with no incoming edges
        queue = deque([step.id for step in steps if in_degree[step.id] == 0])
        sorted_steps = []
        
        while queue:
            current_id = queue.popleft()
            sorted_steps.append(step_map[current_id])
            
            # Reduce in-degree for neighbors
            for neighbor_id in graph[current_id]:
                in_degree[neighbor_id] -= 1
                if in_degree[neighbor_id] == 0:
                    queue.append(neighbor_id)
        
        return sorted_steps
    
    async def define_workflow(self, workflow: Workflow) -> Workflow:
        """Define and validate a workflow."""
        with create_span("define_workflow") as span:
            span.set_attribute("workflow_name", workflow.name)
            
            # Validate DAG
            self.validate_workflow_dag(workflow)
            
            # Store workflow
            self.workflows[workflow.id] = workflow
            
            logger.info(f"İş akışı tanımlandı: {workflow.name} ({workflow.id})")
            
            workflow_counter.labels(
                operation="define",
                status="success"
            ).inc()
            
            return workflow
    
    async def execute_workflow(
        self,
        workflow_id: str,
        input_data: Dict[str, Any],
        options: Optional[ExecutionOptions] = None
    ) -> WorkflowExecution:
        """Execute a workflow."""
        with create_span("execute_workflow") as span:
            workflow = self.workflows.get(workflow_id)
            if not workflow:
                raise ValueError(f"İş akışı bulunamadı: {workflow_id}")
            
            span.set_attribute("workflow_name", workflow.name)
            
            options = options or ExecutionOptions()
            
            # Create execution instance
            execution = WorkflowExecution(
                workflow_id=workflow_id,
                input_data=input_data,
                context=input_data.copy(),
                status=WorkflowStatus.RUNNING
            )
            
            self.executions[execution.id] = execution
            
            try:
                # Sort steps topologically
                sorted_steps = self.topological_sort(workflow.steps)
                
                # Determine entry point
                if workflow.entry_point:
                    entry_step = next((s for s in sorted_steps if s.id == workflow.entry_point), None)
                    if entry_step:
                        sorted_steps = [entry_step] + [s for s in sorted_steps if s.id != workflow.entry_point]
                
                # Execute steps
                for step in sorted_steps:
                    # Check if dependencies are satisfied
                    deps_satisfied = all(
                        dep_id in execution.step_results and 
                        execution.step_results[dep_id].status == StepStatus.COMPLETED
                        for dep_id in step.dependencies
                    )
                    
                    if not deps_satisfied:
                        logger.warning(f"Bağımlılıklar sağlanmadı, adım atlanıyor: {step.name}")
                        continue
                    
                    execution.current_step = step.id
                    
                    # Execute step
                    result = await self.step_executor.execute(
                        step,
                        input_data,
                        execution.context,
                        options
                    )
                    
                    execution.step_results[step.id] = result
                    
                    # Update context with step output
                    if result.output:
                        execution.context[f"step_{step.id}_output"] = result.output
                    
                    # Handle step failure
                    if result.status == StepStatus.FAILED:
                        if step.error_handling == ErrorHandling.FAIL:
                            execution.status = WorkflowStatus.FAILED
                            execution.error = f"Adım başarısız: {step.name}"
                            break
                
                # Execute success/failure handlers
                if execution.status != WorkflowStatus.FAILED:
                    execution.status = WorkflowStatus.COMPLETED
                    if workflow.on_success:
                        await self._execute_handlers(workflow.on_success, execution, options)
                else:
                    if workflow.on_failure:
                        await self._execute_handlers(workflow.on_failure, execution, options)
                
                # Calculate duration
                execution.end_time = datetime.now(UTC)
                execution.duration_ms = (execution.end_time - execution.start_time).total_seconds() * 1000
                
                # Record metrics
                workflow_counter.labels(
                    operation="execute",
                    status="success" if execution.status == WorkflowStatus.COMPLETED else "error"
                ).inc()
                
                workflow_duration_histogram.labels(
                    workflow=workflow.name
                ).observe(execution.duration_ms)
                
                logger.info(
                    f"İş akışı tamamlandı: {workflow.name}, "
                    f"Durum: {execution.status}, "
                    f"Süre: {execution.duration_ms:.2f}ms"
                )
                
                return execution
                
            except Exception as e:
                logger.error(f"İş akışı hatası {workflow.name}: {e}")
                execution.status = WorkflowStatus.FAILED
                execution.error = str(e)
                execution.end_time = datetime.now(UTC)
                execution.duration_ms = (execution.end_time - execution.start_time).total_seconds() * 1000
                
                workflow_counter.labels(
                    operation="execute",
                    status="error"
                ).inc()
                
                return execution
    
    async def _execute_handlers(
        self,
        handler_ids: List[str],
        execution: WorkflowExecution,
        options: ExecutionOptions
    ) -> None:
        """Execute success/failure handlers."""
        for handler_id in handler_ids:
            # Find handler step
            workflow = self.workflows.get(execution.workflow_id)
            if not workflow:
                continue
            
            handler_step = next((s for s in workflow.steps if s.id == handler_id), None)
            if handler_step:
                await self.step_executor.execute(
                    handler_step,
                    execution.input_data,
                    execution.context,
                    options
                )
    
    def get_execution_status(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution status."""
        return self.executions.get(execution_id)
    
    async def pause_execution(self, execution_id: str) -> bool:
        """Pause workflow execution."""
        execution = self.executions.get(execution_id)
        if execution and execution.status == WorkflowStatus.RUNNING:
            execution.status = WorkflowStatus.PAUSED
            logger.info(f"İş akışı duraklatıldı: {execution_id}")
            return True
        return False
    
    async def resume_execution(self, execution_id: str) -> bool:
        """Resume workflow execution."""
        execution = self.executions.get(execution_id)
        if execution and execution.status == WorkflowStatus.PAUSED:
            execution.status = WorkflowStatus.RUNNING
            logger.info(f"İş akışı devam ettirildi: {execution_id}")
            # TODO: Implement actual resume logic
            return True
        return False
    
    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel workflow execution."""
        execution = self.executions.get(execution_id)
        if execution and execution.status in [WorkflowStatus.RUNNING, WorkflowStatus.PAUSED]:
            execution.status = WorkflowStatus.CANCELLED
            execution.end_time = datetime.now(UTC)
            logger.info(f"İş akışı iptal edildi: {execution_id}")
            return True
        return False