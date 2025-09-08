"""
Batch Import/Export Processor for Task 7.20 - Multi-format Pipeline

Provides high-performance batch processing with:
- Parallel batch processing
- Progress tracking
- Error recovery
- Memory-efficient streaming
- Result aggregation
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..core.metrics import batch_counter, batch_duration_histogram
from ..core.telemetry import create_span
from .universal_importer import UniversalImporter, ImportOptions, ImportResult
from .enhanced_exporter import EnhancedExporter, ExportOptions, ExportResult, ExportFormat
from .format_converter import FormatConverter, ConversionOptions, ConversionResult
from .freecad_document_manager import FreeCADDocumentManager

logger = get_logger(__name__)


class BatchOperation(str, Enum):
    """Types of batch operations."""
    IMPORT = "import"
    EXPORT = "export"
    CONVERT = "convert"
    IMPORT_EXPORT = "import_export"
    MULTI_FORMAT_EXPORT = "multi_format_export"


class BatchStrategy(str, Enum):
    """Batch processing strategies."""
    PARALLEL = "parallel"  # Process all in parallel
    SEQUENTIAL = "sequential"  # Process one by one
    CHUNKED = "chunked"  # Process in chunks
    ADAPTIVE = "adaptive"  # Adapt based on system resources


class BatchOptions(BaseModel):
    """Options for batch processing."""
    strategy: BatchStrategy = Field(default=BatchStrategy.ADAPTIVE, description="İşleme stratejisi")
    max_parallel: int = Field(default=4, ge=1, le=32, description="Maksimum paralel işlem")
    chunk_size: int = Field(default=10, ge=1, le=100, description="Chunk boyutu")
    continue_on_error: bool = Field(default=True, description="Hata durumunda devam et")
    retry_failed: bool = Field(default=True, description="Başarısız olanları tekrar dene")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maksimum tekrar sayısı")
    progress_callback: Optional[str] = Field(default=None, description="İlerleme callback URL")
    memory_limit_mb: int = Field(default=2048, ge=512, le=16384, description="Bellek limiti (MB)")
    timeout_per_file: int = Field(default=300, ge=30, le=3600, description="Dosya başına timeout (saniye)")
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "strategy": "adaptive",
            "max_parallel": 4,
            "continue_on_error": True,
            "retry_failed": True,
            "memory_limit_mb": 2048
        }
    ]}}


class BatchProgress(BaseModel):
    """Progress tracking for batch operations."""
    total: int = Field(description="Toplam dosya sayısı")
    processed: int = Field(default=0, description="İşlenen dosya sayısı")
    successful: int = Field(default=0, description="Başarılı dosya sayısı")
    failed: int = Field(default=0, description="Başarısız dosya sayısı")
    skipped: int = Field(default=0, description="Atlanan dosya sayısı")
    current_file: Optional[str] = Field(default=None, description="Şu anki dosya")
    progress_percent: float = Field(default=0.0, description="İlerleme yüzdesi")
    estimated_time_remaining: Optional[float] = Field(default=None, description="Tahmini kalan süre (saniye)")
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    def update(self, processed: int = 0, successful: int = 0, failed: int = 0, skipped: int = 0):
        """Update progress counters."""
        self.processed += processed
        self.successful += successful
        self.failed += failed
        self.skipped += skipped
        self.progress_percent = (self.processed / self.total * 100) if self.total > 0 else 0
        
        # Estimate time remaining
        if self.processed > 0:
            elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            rate = self.processed / elapsed
            remaining = self.total - self.processed
            self.estimated_time_remaining = remaining / rate if rate > 0 else None


class BatchResult(BaseModel):
    """Result of a batch operation."""
    operation: BatchOperation = Field(description="İşlem tipi")
    success: bool = Field(description="Genel başarı durumu")
    total_files: int = Field(description="Toplam dosya sayısı")
    successful_files: int = Field(description="Başarılı dosya sayısı")
    failed_files: int = Field(description="Başarısız dosya sayısı")
    skipped_files: int = Field(description="Atlanan dosya sayısı")
    results: List[Union[ImportResult, ExportResult, ConversionResult]] = Field(
        default_factory=list, description="Detaylı sonuçlar"
    )
    error_summary: Dict[str, List[str]] = Field(default_factory=dict, description="Hata özeti")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="İstatistikler")
    duration_ms: float = Field(description="Toplam süre (ms)")
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "batch_started": "Toplu işlem başladı",
        "batch_completed": "Toplu işlem tamamlandı",
        "processing_file": "Dosya işleniyor",
        "file_completed": "Dosya tamamlandı",
        "error_occurred": "Hata oluştu"
    })


class ResourceMonitor:
    """Monitor system resources for adaptive processing."""
    
    @classmethod
    def get_available_memory(cls) -> int:
        """Get available memory in MB."""
        try:
            import psutil
            return psutil.virtual_memory().available // (1024 * 1024)
        except ImportError:
            # Default to 1GB if psutil not available
            return 1024
    
    @classmethod
    def get_cpu_count(cls) -> int:
        """Get number of CPU cores."""
        import os
        return os.cpu_count() or 4
    
    @classmethod
    def calculate_optimal_parallel(cls, file_count: int, avg_file_size_mb: float) -> int:
        """Calculate optimal parallel processing count."""
        cpu_count = cls.get_cpu_count()
        available_memory = cls.get_available_memory()
        
        # Estimate memory per process
        memory_per_process = avg_file_size_mb * 3  # Rough estimate
        
        # Calculate based on memory
        max_by_memory = max(1, int(available_memory / memory_per_process))
        
        # Calculate based on CPU
        max_by_cpu = min(cpu_count * 2, 8)  # Don't oversubscribe too much
        
        # Take minimum and apply bounds
        optimal = min(max_by_memory, max_by_cpu, file_count)
        return max(1, min(optimal, 16))  # Between 1 and 16


class BatchProcessor:
    """High-performance batch processor for import/export operations."""
    
    def __init__(
        self,
        importer: Optional[UniversalImporter] = None,
        exporter: Optional[EnhancedExporter] = None,
        converter: Optional[FormatConverter] = None,
        document_manager: Optional[FreeCADDocumentManager] = None
    ):
        """
        Initialize batch processor.
        
        Args:
            importer: Universal importer instance
            exporter: Enhanced exporter instance
            converter: Format converter instance
            document_manager: Document manager instance
        """
        self.importer = importer or UniversalImporter()
        self.exporter = exporter or EnhancedExporter()
        self.converter = converter or FormatConverter()
        self.document_manager = document_manager or FreeCADDocumentManager()
        self._semaphore = None
        self._progress = None
    
    async def batch_import(
        self,
        file_paths: List[Union[str, Path]],
        options: Optional[BatchOptions] = None,
        import_options: Optional[ImportOptions] = None,
        job_id_prefix: str = "batch"
    ) -> BatchResult:
        """
        Batch import multiple files.
        
        Args:
            file_paths: List of file paths to import
            options: Batch processing options
            import_options: Import options for each file
            job_id_prefix: Prefix for job IDs
            
        Returns:
            Batch result with detailed information
        """
        with create_span("batch_import") as span:
            span.set_attribute("file_count", len(file_paths))
            
            start_time = asyncio.get_event_loop().time()
            options = options or BatchOptions()
            import_options = import_options or ImportOptions()
            
            result = BatchResult(
                operation=BatchOperation.IMPORT,
                success=False,
                total_files=len(file_paths),
                successful_files=0,
                failed_files=0,
                skipped_files=0,
                duration_ms=0
            )
            
            # Initialize progress
            self._progress = BatchProgress(total=len(file_paths))
            
            try:
                # Determine processing strategy
                if options.strategy == BatchStrategy.ADAPTIVE:
                    # Calculate average file size asynchronously
                    file_sizes = await asyncio.gather(*[
                        asyncio.to_thread(lambda p: p.stat().st_size if p.exists() else 0, Path(fp))
                        for fp in file_paths
                    ])
                    total_size = sum(file_sizes)
                    avg_size_mb = (total_size / len(file_paths) / (1024 * 1024)) if file_paths else 1
                    max_parallel = ResourceMonitor.calculate_optimal_parallel(
                        len(file_paths), avg_size_mb
                    )
                else:
                    max_parallel = options.max_parallel
                
                self._semaphore = asyncio.Semaphore(max_parallel)
                
                # Process files
                if options.strategy == BatchStrategy.SEQUENTIAL:
                    results = await self._process_sequential(
                        file_paths, self._import_single, import_options, job_id_prefix, options
                    )
                elif options.strategy == BatchStrategy.CHUNKED:
                    results = await self._process_chunked(
                        file_paths, self._import_single, import_options, job_id_prefix, options
                    )
                else:  # PARALLEL or ADAPTIVE
                    results = await self._process_parallel(
                        file_paths, self._import_single, import_options, job_id_prefix, options
                    )
                
                # Aggregate results
                for r in results:
                    if r:
                        result.results.append(r)
                        if r.success:
                            result.successful_files += 1
                        else:
                            result.failed_files += 1
                            for error in r.errors:
                                file_name = Path(r.file_path).name
                                if file_name not in result.error_summary:
                                    result.error_summary[file_name] = []
                                result.error_summary[file_name].append(error)
                    else:
                        result.skipped_files += 1
                
                result.success = result.successful_files > 0
                
                # Collect statistics
                result.statistics = self._collect_statistics(result.results)
                
                # Record metrics
                batch_counter.labels(
                    operation="import",
                    status="success" if result.success else "error"
                ).inc()
                
            except Exception as e:
                logger.error(f"Toplu içe aktarma hatası: {e}")
                result.error_summary["general"] = [str(e)]
                
                batch_counter.labels(
                    operation="import",
                    status="error"
                ).inc()
            
            finally:
                # Calculate duration
                result.duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                batch_duration_histogram.labels(
                    operation="import"
                ).observe(result.duration_ms)
                
                span.set_attribute("success", result.success)
                span.set_attribute("duration_ms", result.duration_ms)
            
            return result
    
    async def batch_export(
        self,
        documents: List[Any],
        output_dir: Union[str, Path],
        formats: List[ExportFormat],
        options: Optional[BatchOptions] = None,
        export_options: Optional[ExportOptions] = None
    ) -> BatchResult:
        """
        Batch export multiple documents.
        
        Args:
            documents: List of FreeCAD documents
            output_dir: Output directory
            formats: Export formats
            options: Batch processing options
            export_options: Export options
            
        Returns:
            Batch result
        """
        with create_span("batch_export") as span:
            span.set_attribute("document_count", len(documents))
            span.set_attribute("format_count", len(formats))
            
            start_time = asyncio.get_event_loop().time()
            options = options or BatchOptions()
            export_options = export_options or ExportOptions()
            output_dir = Path(output_dir)
            
            # Create output directory if needed
            output_dir.mkdir(parents=True, exist_ok=True)
            
            result = BatchResult(
                operation=BatchOperation.EXPORT,
                success=False,
                total_files=len(documents) * len(formats),
                successful_files=0,
                failed_files=0,
                skipped_files=0,
                duration_ms=0
            )
            
            # Initialize progress
            self._progress = BatchProgress(total=result.total_files)
            
            try:
                # Prepare export tasks
                export_tasks = []
                for doc in documents:
                    doc_name = doc.Name if hasattr(doc, "Name") else f"doc_{id(doc)}"
                    for format in formats:
                        output_path = output_dir / f"{doc_name}.{format.value}"
                        export_tasks.append((doc, output_path, format))
                
                # Determine max parallel
                if options.strategy == BatchStrategy.ADAPTIVE:
                    max_parallel = ResourceMonitor.calculate_optimal_parallel(
                        len(export_tasks), 10  # Assume 10MB average
                    )
                else:
                    max_parallel = options.max_parallel
                
                self._semaphore = asyncio.Semaphore(max_parallel)
                
                # Process exports
                if options.strategy == BatchStrategy.SEQUENTIAL:
                    results = await self._process_sequential(
                        export_tasks, self._export_single, export_options, None, options
                    )
                elif options.strategy == BatchStrategy.CHUNKED:
                    results = await self._process_chunked(
                        export_tasks, self._export_single, export_options, None, options
                    )
                else:
                    results = await self._process_parallel(
                        export_tasks, self._export_single, export_options, None, options
                    )
                
                # Aggregate results
                for r in results:
                    if r:
                        result.results.append(r)
                        if r.success:
                            result.successful_files += 1
                        else:
                            result.failed_files += 1
                            for error in r.errors:
                                file_name = Path(r.file_path).name
                                if file_name not in result.error_summary:
                                    result.error_summary[file_name] = []
                                result.error_summary[file_name].append(error)
                    else:
                        result.skipped_files += 1
                
                result.success = result.successful_files > 0
                result.statistics = self._collect_statistics(result.results)
                
                batch_counter.labels(
                    operation="export",
                    status="success" if result.success else "error"
                ).inc()
                
            except Exception as e:
                logger.error(f"Toplu dışa aktarma hatası: {e}")
                result.error_summary["general"] = [str(e)]
                
                batch_counter.labels(
                    operation="export",
                    status="error"
                ).inc()
            
            finally:
                result.duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                batch_duration_histogram.labels(
                    operation="export"
                ).observe(result.duration_ms)
                
                span.set_attribute("success", result.success)
                span.set_attribute("duration_ms", result.duration_ms)
            
            return result
    
    async def batch_convert(
        self,
        conversions: List[Dict[str, Any]],
        options: Optional[BatchOptions] = None,
        conversion_options: Optional[ConversionOptions] = None
    ) -> BatchResult:
        """
        Batch convert files.
        
        Args:
            conversions: List of conversion specs with input/output/formats
            options: Batch processing options
            conversion_options: Conversion options
            
        Returns:
            Batch result
        """
        with create_span("batch_convert") as span:
            span.set_attribute("conversion_count", len(conversions))
            
            start_time = asyncio.get_event_loop().time()
            options = options or BatchOptions()
            conversion_options = conversion_options or ConversionOptions()
            
            result = BatchResult(
                operation=BatchOperation.CONVERT,
                success=False,
                total_files=len(conversions),
                successful_files=0,
                failed_files=0,
                skipped_files=0,
                duration_ms=0
            )
            
            # Initialize progress
            self._progress = BatchProgress(total=len(conversions))
            
            try:
                # Determine max parallel
                if options.strategy == BatchStrategy.ADAPTIVE:
                    max_parallel = ResourceMonitor.calculate_optimal_parallel(len(conversions), 20)
                else:
                    max_parallel = options.max_parallel
                
                self._semaphore = asyncio.Semaphore(max_parallel)
                
                # Process conversions
                if options.strategy == BatchStrategy.SEQUENTIAL:
                    results = await self._process_sequential(
                        conversions, self._convert_single, conversion_options, None, options
                    )
                elif options.strategy == BatchStrategy.CHUNKED:
                    results = await self._process_chunked(
                        conversions, self._convert_single, conversion_options, None, options
                    )
                else:
                    results = await self._process_parallel(
                        conversions, self._convert_single, conversion_options, None, options
                    )
                
                # Aggregate results
                for r in results:
                    if r:
                        result.results.append(r)
                        if r.success:
                            result.successful_files += 1
                        else:
                            result.failed_files += 1
                            for error in r.errors:
                                if r.input_file not in result.error_summary:
                                    result.error_summary[r.input_file] = []
                                result.error_summary[r.input_file].append(error)
                    else:
                        result.skipped_files += 1
                
                result.success = result.successful_files > 0
                result.statistics = self._collect_statistics(result.results)
                
                batch_counter.labels(
                    operation="convert",
                    status="success" if result.success else "error"
                ).inc()
                
            except Exception as e:
                logger.error(f"Toplu dönüştürme hatası: {e}")
                result.error_summary["general"] = [str(e)]
                
                batch_counter.labels(
                    operation="convert",
                    status="error"
                ).inc()
            
            finally:
                result.duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                batch_duration_histogram.labels(
                    operation="convert"
                ).observe(result.duration_ms)
                
                span.set_attribute("success", result.success)
                span.set_attribute("duration_ms", result.duration_ms)
            
            return result
    
    async def _import_single(
        self,
        file_path: Union[str, Path],
        import_options: ImportOptions,
        job_id_prefix: str,
        batch_options: BatchOptions
    ) -> Optional[ImportResult]:
        """Import single file with error handling."""
        async with self._semaphore:
            try:
                file_path = Path(file_path)
                self._progress.current_file = file_path.name
                
                # Generate job ID as int using stable hash
                # hashlib already imported at module level
                job_id_hash = hashlib.sha256(f"{job_id_prefix}_{file_path.stem}_{file_path}".encode()).hexdigest()
                job_id = int(job_id_hash[:16], 16)
                
                # Import with timeout
                result = await asyncio.wait_for(
                    self.importer.import_file(file_path, job_id, import_options),
                    timeout=batch_options.timeout_per_file
                )
                
                self._progress.update(processed=1, successful=1 if result.success else 0,
                                    failed=0 if result.success else 1)
                
                return result
                
            except asyncio.TimeoutError:
                logger.error(f"İçe aktarma zaman aşımı: {file_path}")
                self._progress.update(processed=1, failed=1)
                return None
            except Exception as e:
                logger.error(f"İçe aktarma hatası {file_path}: {e}")
                self._progress.update(processed=1, failed=1)
                
                if batch_options.retry_failed:
                    # Retry logic
                    for retry in range(batch_options.max_retries):
                        try:
                            await asyncio.sleep(2 ** retry)  # Exponential backoff
                            result = await self.importer.import_file(file_path, job_id, import_options)
                            if result.success:
                                self._progress.update(successful=1, failed=-1)
                                return result
                        except Exception:
                            continue
                
                return None if batch_options.continue_on_error else None
    
    async def _export_single(
        self,
        task: Tuple[Any, Path, ExportFormat],
        export_options: ExportOptions,
        _: Any,
        batch_options: BatchOptions
    ) -> Optional[ExportResult]:
        """Export single document with error handling."""
        async with self._semaphore:
            try:
                document, output_path, format = task
                self._progress.current_file = output_path.name
                
                # Export with timeout
                result = await asyncio.wait_for(
                    self.exporter.export_with_validation(document, output_path, format, export_options),
                    timeout=batch_options.timeout_per_file
                )
                
                self._progress.update(processed=1, successful=1 if result.success else 0,
                                    failed=0 if result.success else 1)
                
                return result
                
            except asyncio.TimeoutError:
                logger.error(f"Dışa aktarma zaman aşımı: {output_path}")
                self._progress.update(processed=1, failed=1)
                return None
            except Exception as e:
                logger.error(f"Dışa aktarma hatası {output_path}: {e}")
                self._progress.update(processed=1, failed=1)
                return None if batch_options.continue_on_error else None
    
    async def _convert_single(
        self,
        spec: Dict[str, Any],
        conversion_options: ConversionOptions,
        _: Any,
        batch_options: BatchOptions
    ) -> Optional[ConversionResult]:
        """Convert single file with error handling."""
        async with self._semaphore:
            try:
                input_file = Path(spec["input"])
                output_file = Path(spec["output"])
                self._progress.current_file = input_file.name
                
                # Convert with timeout
                result = await asyncio.wait_for(
                    self.converter.convert(
                        input_file,
                        output_file,
                        spec.get("source_format"),
                        spec.get("target_format"),
                        conversion_options,
                        job_id=int(hashlib.sha256(str(input_file).encode()).hexdigest()[:16], 16)
                    ),
                    timeout=batch_options.timeout_per_file
                )
                
                self._progress.update(processed=1, successful=1 if result.success else 0,
                                    failed=0 if result.success else 1)
                
                return result
                
            except asyncio.TimeoutError:
                logger.error(f"Dönüştürme zaman aşımı: {input_file}")
                self._progress.update(processed=1, failed=1)
                return None
            except Exception as e:
                logger.error(f"Dönüştürme hatası {input_file}: {e}")
                self._progress.update(processed=1, failed=1)
                return None if batch_options.continue_on_error else None
    
    async def _process_sequential(
        self,
        items: List[Any],
        processor: callable,
        process_options: Any,
        job_id_prefix: Optional[str],
        batch_options: BatchOptions
    ) -> List[Any]:
        """Process items sequentially."""
        results = []
        for item in items:
            result = await processor(item, process_options, job_id_prefix, batch_options)
            results.append(result)
        return results
    
    async def _process_parallel(
        self,
        items: List[Any],
        processor: callable,
        process_options: Any,
        job_id_prefix: Optional[str],
        batch_options: BatchOptions
    ) -> List[Any]:
        """Process items in parallel."""
        tasks = []
        for item in items:
            task = asyncio.create_task(
                processor(item, process_options, job_id_prefix, batch_options)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions if continue_on_error
        if batch_options.continue_on_error:
            return [r for r in results if not isinstance(r, Exception)]
        return results
    
    async def _process_chunked(
        self,
        items: List[Any],
        processor: callable,
        process_options: Any,
        job_id_prefix: Optional[str],
        batch_options: BatchOptions
    ) -> List[Any]:
        """Process items in chunks."""
        results = []
        chunk_size = batch_options.chunk_size
        
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            chunk_results = await self._process_parallel(
                chunk, processor, process_options, job_id_prefix, batch_options
            )
            results.extend(chunk_results)
        
        return results
    
    def _collect_statistics(self, results: List[Any]) -> Dict[str, Any]:
        """Collect statistics from results."""
        stats = {
            "total_processed": len(results),
            "by_format": defaultdict(int),
            "total_size_mb": 0,
            "avg_processing_time_ms": 0,
            "min_processing_time_ms": float('inf'),
            "max_processing_time_ms": 0
        }
        
        total_time = 0
        for result in results:
            if hasattr(result, "format"):
                stats["by_format"][result.format] += 1
            
            if hasattr(result, "file_size"):
                stats["total_size_mb"] += result.file_size / (1024 * 1024)
            
            # Get processing time based on result type
            if hasattr(result, "import_time_ms"):
                time_ms = result.import_time_ms
            elif hasattr(result, "export_time_ms"):
                time_ms = result.export_time_ms
            elif hasattr(result, "conversion_time_ms"):
                time_ms = result.conversion_time_ms
            else:
                time_ms = 0
            
            total_time += time_ms
            stats["min_processing_time_ms"] = min(stats["min_processing_time_ms"], time_ms)
            stats["max_processing_time_ms"] = max(stats["max_processing_time_ms"], time_ms)
        
        if results:
            stats["avg_processing_time_ms"] = total_time / len(results)
        
        if stats["min_processing_time_ms"] == float('inf'):
            stats["min_processing_time_ms"] = 0
        
        return stats
    
    def get_progress(self) -> Optional[BatchProgress]:
        """Get current batch progress."""
        return self._progress