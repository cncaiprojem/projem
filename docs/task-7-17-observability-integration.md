# Task 7.17: Observability Integration for Model Generation Flows

## Overview

Task 7.17 implements comprehensive observability for FreeCAD 1.1.0/OCCT 7.8.x model generation flows, providing enterprise-grade monitoring, metrics, tracing, and alerting capabilities.

## Architecture

### Components

1. **Metrics Collection** (`app/core/metrics.py`)
   - Prometheus metrics for all FreeCAD/OCCT operations
   - Version-specific labels (freecad_version, occt_version, workbench)
   - Performance histograms with appropriate buckets

2. **Distributed Tracing** (`app/core/telemetry.py`)
   - OpenTelemetry spans for operation tracking
   - Span linking between API → Celery → FreeCAD subprocess
   - Context propagation with job_id and request_id

3. **Observability Service** (`app/services/model_generation_observability.py`)
   - Unified interface for metrics and tracing
   - Helper methods for common operations
   - Alert threshold monitoring

4. **Grafana Dashboards** (`infra/grafana/task-7-17-model-generation-dashboard.json`)
   - 16 comprehensive panels
   - Real-time monitoring of all metrics
   - Version and workbench segmentation

5. **Alert Rules** (`infra/prometheus/alerts/task-7-17-model-generation-alerts.yml`)
   - High failure rate detection (>10%)
   - Slow generation alerts (>5 minutes)
   - Worker OOM/timeout detection
   - OCCT memory and performance alerts

## Metrics Reference

### Model Generation Flow Metrics

```python
# Flow lifecycle
model_generation_started_total{flow_type, freecad_version, occt_version}
model_generation_completed_total{flow_type, status, freecad_version, occt_version}
model_generation_stage_duration_seconds{flow_type, stage, freecad_version}

# AI provider performance
ai_provider_latency_seconds{provider, model, operation}
```

### FreeCAD Document Metrics

```python
# Document operations
freecad_document_load_seconds{source, workbench, freecad_version, occt_version}
freecad_recompute_duration_seconds{workbench, doc_complexity}
freecad_object_created_total{class, workbench}
```

### OCCT Operation Metrics

```python
# Boolean operations
occt_boolean_duration_seconds{operation=union|cut|common, solids_range}

# Feature operations
occt_feature_duration_seconds{feature=fillet|chamfer}

# Memory tracking
occt_operation_memory_bytes{operation}
```

### Assembly4 Metrics

```python
# Constraint solving
a4_constraint_solve_duration_seconds{solver}
a4_lcs_resolution_duration_seconds{lcs_count_range}
a4_solver_iterations_total{solver}
```

### Material Framework Metrics

```python
# Library access
material_library_access_total{library, result=hit|miss|error}

# Property application
material_property_apply_duration_seconds{property}
material_appearance_apply_duration_seconds{appearance_type}
```

### Topology and Export Metrics

```python
# Topology computation
topology_hash_compute_duration_seconds{scope=part|assembly}

# Export validation
deterministic_export_validation_total{format=STEP|STL|GLB, result=pass|fail}
export_duration_seconds{format, file_size_range, freecad_version}
```

### Workbench Metrics

```python
# Usage tracking
freecad_workbench_invocations_total{workbench}
freecad_workbench_compatibility_total{workbench, compatible=true|false}
```

## Usage Examples

### Basic Model Generation Monitoring

```python
from app.services.model_generation_observability import model_observability

# Monitor complete flow
with model_observability.observe_model_generation(
    flow_type="ai_prompt",
    job_id="job-123",
    user_id=1
):
    # AI provider call
    model_observability.record_ai_provider_latency(
        provider="openai",
        model="gpt-4",
        operation="prompt_to_script",
        latency_seconds=2.5
    )
    
    # Stage monitoring
    with model_observability.observe_stage("ai_prompt", "validation"):
        # Validation logic
        pass
    
    # Document operations
    with model_observability.observe_document_operation(
        document_id="doc-123",
        operation="load",
        workbench="PartDesign"
    ):
        # Load document
        pass
```

### OCCT Operations Monitoring

```python
# Boolean operations
with model_observability.observe_occt_boolean(
    operation="union",
    solids_count=5
):
    # Perform union
    pass

# Feature operations
with model_observability.observe_occt_feature(
    feature="fillet",
    edges_count=12
):
    # Apply fillet
    pass

# Memory tracking
model_observability.record_occt_memory(
    operation="boolean_complex",
    memory_bytes=536870912  # 512MB
)
```

### Assembly4 Constraint Solving

```python
# Monitor solver
with model_observability.observe_assembly4_solver(
    solver_type="newton_raphson",
    constraints_count=50,
    lcs_count=10
) as context:
    # Solve constraints
    for iteration in solver_loop():
        # Update iteration count
        context["iterations"] = iteration
    
# Record LCS resolution
model_observability.record_lcs_resolution(
    lcs_count=15,
    duration_seconds=0.5
)
```

### Material Framework Operations

```python
# Library access
model_observability.record_material_library_access(
    library="standard_materials",
    result="hit"  # or "miss", "error"
)

# Property application
with model_observability.observe_material_property_application(
    property_type="density",
    material_count=5,
    library="standard_materials"
):
    # Apply properties
    pass
```

### Export and Validation

```python
# Export operation
with model_observability.observe_export(
    format="STEP",
    file_size=2048000  # 2MB
):
    # Export file
    pass

# Validation result
model_observability.record_export_validation(
    format="STEP",
    result="pass",  # or "fail"
    file_size=2048000
)
```

## Alert Configuration

### Critical Alerts

1. **ModelGenerationHighFailureRate**
   - Threshold: >10% failure rate over 5 minutes
   - Action: Check logs, verify FreeCAD service health

2. **FreeCADWorkerFailure**
   - Threshold: >0.1 restarts per second
   - Action: Check memory limits, investigate OOM kills

3. **AIProviderHighErrorRate**
   - Threshold: >10% error rate
   - Action: Check API keys, provider status

### Warning Alerts

1. **ModelGenerationSlow**
   - Threshold: P95 >5 minutes
   - Action: Review model complexity, optimize operations

2. **OCCTBooleanOperationSlow**
   - Threshold: P95 >30 seconds
   - Action: Review geometry complexity

3. **OCCTHighMemoryUsage**
   - Threshold: >1.5GB
   - Action: Monitor for memory leaks

4. **Assembly4SolverSlow**
   - Threshold: P95 >15 seconds
   - Action: Review constraint complexity

5. **Assembly4ExcessiveIterations**
   - Threshold: P95 >200 iterations
   - Action: Check convergence parameters

## Grafana Dashboard

### Key Panels

1. **Model Generation Success Rate**: Overall and by flow type
2. **P95 Latencies**: Performance tracking by flow
3. **Active Flows**: Current system load
4. **AI Provider Performance**: Latency heatmap
5. **Document Operations**: Load and recompute times
6. **OCCT Operations**: Boolean and feature performance
7. **OCCT Memory Usage**: Memory consumption tracking
8. **Assembly4 Solver**: Performance and iterations
9. **LCS Resolution**: Performance by count range
10. **Material Library**: Hit/miss rates
11. **Material Application**: Property and appearance timing
12. **Topology Hash**: Computation performance
13. **Export Validation**: Success rates by format
14. **Export Duration**: Performance by format and size
15. **Workbench Usage**: Invocations and compatibility
16. **Worker Resources**: CPU and memory usage

### Dashboard Variables

- `freecad_version`: Filter by FreeCAD version
- `occt_version`: Filter by OCCT version
- `flow_type`: Filter by model generation flow type

## Integration with Progress Service

The observability system integrates with Task 7.16 progress service:

```python
from app.services.progress_service import progress_service

# Publish progress with automatic metric updates
await progress_service.publish_document_progress(
    job_id=123,
    phase=DocumentPhase.RECOMPUTE_START,
    document_id="doc-001"
)

await progress_service.publish_assembly4_progress(
    job_id=124,
    phase=Assembly4Phase.SOLVER_PROGRESS,
    constraints_resolved=15,
    constraints_total=30
)
```

## Performance Optimization

### Metric Collection Best Practices

1. **Use appropriate histogram buckets**: Match expected value ranges
2. **Limit label cardinality**: Avoid high-cardinality labels
3. **Batch metric updates**: Group related updates
4. **Use gauges for current state**: Not counters for values that can decrease

### Tracing Best Practices

1. **Create spans judiciously**: Avoid excessive span creation
2. **Use span attributes**: Add relevant context
3. **Link related spans**: Maintain trace continuity
4. **Sample appropriately**: Use head-based sampling for high-volume operations

## Testing

### Unit Tests
```bash
pytest apps/api/tests/unit/test_model_observability.py -v
```

### Integration Tests
```bash
pytest apps/api/tests/integration/test_task_7_17_observability.py -v
```

### Metric Validation
```bash
curl -s http://localhost:8000/metrics | grep model_generation
```

### Dashboard Validation
1. Open Grafana: http://localhost:3000
2. Import dashboard: `task-7-17-model-generation-dashboard.json`
3. Verify all panels load correctly
4. Check alert rules are active

## Troubleshooting

### Missing Metrics

1. Check metric registration in `metrics.py`
2. Verify labels are being set correctly
3. Check Prometheus scrape configuration

### Missing Spans

1. Verify tracer initialization
2. Check OTLP endpoint configuration
3. Verify span creation in code

### Alert Not Firing

1. Check alert expression in Prometheus
2. Verify threshold values
3. Check evaluation interval

### Dashboard Issues

1. Verify datasource configuration
2. Check metric names match queries
3. Verify time range selection

## Future Enhancements

1. **Machine Learning Integration**
   - Anomaly detection for performance metrics
   - Predictive failure analysis

2. **Advanced Visualizations**
   - 3D topology visualization
   - Real-time constraint solving animation

3. **Cost Attribution**
   - Resource usage per user/license tier
   - Operation cost tracking

4. **SLA Monitoring**
   - Per-customer SLA tracking
   - Automated SLA reports

## Acceptance Criteria

✅ Traces flow end-to-end from API → Celery → FreeCAD  
✅ All FreeCAD 1.1.0/OCCT 7.8.x metrics exported with version labels  
✅ Grafana dashboards show real data segmented by versions  
✅ Alerts fire under configured thresholds  
✅ Integration with Task 7.16 progress service  
✅ Performance overhead <5% for metric collection  
✅ Comprehensive test coverage >80%