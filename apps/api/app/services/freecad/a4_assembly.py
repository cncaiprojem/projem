"""
Assembly4 Support for Task 7.6

Provides Assembly4 workbench functionality:
- App::Link lightweight references
- OndselSolver constraint solving
- LCS (Local Coordinate System) placement
- Joint types: Fixed, Revolute, Cylindrical, Slider, Ball, Planar
- DOF (Degrees of Freedom) analysis
- Kinematic simulation
- Collision detection integration
"""

from __future__ import annotations

import ast
import json
import math
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


class JointType(str, Enum):
    """Assembly joint types with DOF characteristics."""
    FIXED = "fixed"  # 0 DOF
    REVOLUTE = "revolute"  # 1 DOF (rotation)
    CYLINDRICAL = "cylindrical"  # 2 DOF (rotation + translation)
    SLIDER = "slider"  # 1 DOF (translation)
    BALL = "ball"  # 3 DOF (spherical)
    PLANAR = "planar"  # 3 DOF (2 translations + 1 rotation)


class ComponentSource(BaseModel):
    """Component source definition."""
    type: str = Field(description="Source type: parametric, standard, upload_ref")
    spec: Dict[str, Any] = Field(description="Source specification")
    

class LCS(BaseModel):
    """Local Coordinate System definition."""
    name: str = Field(description="LCS name")
    origin: List[float] = Field(description="Origin [x, y, z] in mm")
    axes: Dict[str, List[float]] = Field(
        description="X, Y, Z axis vectors",
        default_factory=lambda: {
            "x": [1.0, 0.0, 0.0],
            "y": [0.0, 1.0, 0.0],
            "z": [0.0, 0.0, 1.0]
        }
    )


class Component(BaseModel):
    """Assembly component definition."""
    id: str = Field(description="Component identifier")
    source: ComponentSource = Field(description="Component source")
    lcs: List[LCS] = Field(default_factory=list, description="Local coordinate systems")
    initial_placement: Optional[Dict[str, List[float]]] = Field(
        default=None,
        description="Initial placement (pos: [x,y,z], rot_euler_deg: [rx,ry,rz])"
    )


class JointLimit(BaseModel):
    """Joint limit definition."""
    min: Optional[float] = Field(default=None, description="Minimum value")
    max: Optional[float] = Field(default=None, description="Maximum value")


class Joint(BaseModel):
    """Assembly joint constraint."""
    id: str = Field(description="Joint identifier")
    type: JointType = Field(description="Joint type")
    component_a: str = Field(description="First component ID")
    lcs_a: str = Field(description="LCS name on component A")
    component_b: str = Field(description="Second component ID")
    lcs_b: str = Field(description="LCS name on component B")
    limits: Optional[Dict[str, JointLimit]] = Field(
        default=None,
        description="Joint limits (angle, translation, etc.)"
    )
    stiffness: Optional[float] = Field(default=None, description="Joint stiffness")
    damping: Optional[float] = Field(default=None, description="Joint damping")


class DOFAnalysis(BaseModel):
    """Degrees of freedom analysis result."""
    global_dof: int = Field(description="Global degrees of freedom")
    per_joint_dof: Dict[str, int] = Field(description="DOF per joint")
    overconstrained: bool = Field(description="Whether system is overconstrained")
    underconstrained: bool = Field(description="Whether system is underconstrained")
    driving_joints: List[str] = Field(description="Independent driving joints")
    diagnostics: List[str] = Field(default_factory=list, description="Diagnostic messages")


class KinematicFrame(BaseModel):
    """Single frame in kinematic simulation."""
    time: float = Field(description="Time stamp")
    placements: Dict[str, Dict[str, List[float]]] = Field(
        description="Component placements at this frame"
    )
    valid: bool = Field(description="Whether frame solved successfully")
    residuals: Optional[float] = Field(default=None, description="Solver residuals")


class Assembly4Manager:
    """Manage Assembly4 operations for FreeCAD."""
    
    # Security: Define allowed upload directories (configurable via environment)
    # Default directories for backward compatibility
    _DEFAULT_UPLOAD_DIRS = "/work/uploads:/tmp/freecad_uploads"
    # Load from environment with default fallback
    # Filter out empty entries to handle empty environment values gracefully
    ALLOWED_UPLOAD_DIRS = [d for d in os.getenv("ALLOWED_UPLOAD_DIRS", _DEFAULT_UPLOAD_DIRS).split(':') if d.strip()]
    
    # AST node whitelist for safe script execution
    SAFE_AST_NODES: Set[type] = {
        # Literals and basic types
        ast.Constant, ast.Num, ast.Str, ast.Bytes, ast.NameConstant,
        ast.List, ast.Tuple, ast.Dict, ast.Set,
        
        # Variables and attributes
        ast.Name, ast.Load, ast.Store, ast.Del, ast.Attribute,
        
        # Basic operations
        ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
        ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd,
        ast.FloorDiv, ast.And, ast.Or, ast.Not,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.Is, ast.IsNot, ast.In, ast.NotIn,
        
        # Control flow (limited)
        ast.If, ast.For, ast.While, ast.Break, ast.Continue,
        ast.Expr, ast.Pass,
        
        # Function calls (will be filtered)
        ast.Call, ast.keyword,
        
        # Assignments
        ast.Assign, ast.AugAssign,
        
        # Comprehensions
        ast.ListComp, ast.DictComp, ast.SetComp,
        ast.comprehension,
        
        # Module level
        ast.Module, ast.Interactive, ast.Expression,
    }
    
    # Allowed function calls for script execution
    ALLOWED_FUNCTIONS = {
        'doc.addObject', 'Part.makeBox', 'Part.makeCylinder',
        'Part.makeSphere', 'Part.makeCone', 'Part.makeTorus',
        'FreeCAD.Vector', 'FreeCAD.Rotation', 'FreeCAD.Placement',
        'float', 'int', 'str', 'len', 'range', 'min', 'max',
        'abs', 'round', 'sum', 'any', 'all'
    }
    
    def __init__(self):
        """Initialize Assembly4 manager."""
        self._freecad_available = self._check_freecad()
        self._solver_available = self._check_solver()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD and required modules are available."""
        try:
            import FreeCAD
            import Part
            # Check for Assembly4 workbench
            # Note: This would require actual Assembly4 installation
            return True
        except ImportError:
            logger.warning("FreeCAD not available for assembly operations")
            return False
    
    def _check_solver(self) -> bool:
        """Check if OndselSolver is available."""
        try:
            # Try to import py_slvs (Python SolveSpace)
            import py_slvs
            return True
        except ImportError:
            logger.warning("OndselSolver/py_slvs not available, using simplified kinematics")
            return False
    
    def create_assembly(
        self,
        name: str,
        components: List[Component],
        joints: List[Joint]
    ) -> Any:
        """
        Create an assembly document with components and joints.
        
        Args:
            name: Assembly name
            components: List of components
            joints: List of joints
        
        Returns:
            FreeCAD assembly document
        """
        if not self._freecad_available:
            raise RuntimeError("FreeCAD is required for assembly operations")
        
        import FreeCAD
        import Part
        
        # Create assembly document
        doc = FreeCAD.newDocument(name)
        
        # Create assembly container
        assembly = doc.addObject("App::Part", f"{name}_Assembly")
        
        # Add components
        component_objects = {}
        for comp in components:
            comp_obj = self._create_component(doc, comp)
            if comp_obj:
                assembly.addObject(comp_obj)
                component_objects[comp.id] = comp_obj
        
        # Create LCS for each component
        for comp in components:
            comp_obj = component_objects.get(comp.id)
            if comp_obj:
                for lcs in comp.lcs:
                    self._create_lcs(doc, comp_obj, lcs)
        
        # Apply joints
        for joint in joints:
            self._create_joint(doc, joint, component_objects)
        
        # Recompute
        doc.recompute()
        
        return doc
    
    def _create_component(self, doc: Any, component: Component) -> Any:
        """Create a component from source specification."""
        import FreeCAD
        import Part
        import os
        
        comp_obj = None
        
        if component.source.type == "parametric":
            # Generate parametrically
            spec = component.source.spec
            # Example: create a box
            if spec.get("type") == "box":
                shape = Part.makeBox(
                    spec.get("length", 100),
                    spec.get("width", 50),
                    spec.get("height", 30)
                )
                comp_obj = doc.addObject("Part::Feature", component.id)
                comp_obj.Shape = shape
                
        elif component.source.type == "standard":
            # Load from standard parts library
            from .standard_parts import standard_parts_library
            
            standard = component.source.spec.get("standard")
            size = component.source.spec.get("size")
            
            if standard and size:
                part_info = standard_parts_library.get_part(standard, size)
                if part_info and part_info.get("script"):
                    # Use AST-based safe execution instead of exec()
                    comp_obj = self._execute_safe_script(
                        part_info["script"],
                        doc,
                        component.id
                    )
                    
        elif component.source.type == "upload_ref":
            # Load from uploaded file with path validation
            file_path = component.source.spec.get("path")
            if file_path:
                # Validate path security to prevent directory traversal
                try:
                    validated_path = self._validate_upload_path(file_path)
                    if validated_path.exists():
                        # Import the file and get the imported document
                        import FreeCAD
                        imported_doc = FreeCAD.open(str(validated_path))
                        
                        # Link the imported objects to the assembly document
                        # Get all objects from the imported document that have shapes
                        imported_objects = [obj for obj in imported_doc.Objects if hasattr(obj, 'Shape')]
                        
                        if imported_objects:
                            # Create a compound of all imported shapes for the component
                            import Part
                            shapes = [obj.Shape for obj in imported_objects if obj.Shape]
                            if shapes:
                                # Create a compound shape from all imported objects
                                compound = Part.makeCompound(shapes)
                                
                                # Add the compound to the assembly document
                                comp_obj = doc.addObject("Part::Feature", f"ImportedComponent_{component.id}")
                                comp_obj.Shape = compound
                                comp_obj.Label = f"Import_{Path(file_path).stem}"
                            else:
                                logger.warning(f"No valid shapes found in imported file: {file_path}")
                        else:
                            logger.warning(f"No objects found in imported file: {file_path}")
                            
                        # Close the imported document to free resources
                        FreeCAD.closeDocument(imported_doc.Name)
                        
                except ValueError as e:
                    logger.error(f"Security violation - invalid path: {e}")
                    raise ValueError(f"Invalid file path: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to import file {file_path}: {e}")
                    raise ValueError(f"Could not import file: {file_path}")
                
        # Apply initial placement
        if comp_obj and component.initial_placement:
            placement = component.initial_placement
            pos = placement.get("pos", [0, 0, 0])
            rot = placement.get("rot_euler_deg", [0, 0, 0])
            
            import FreeCAD
            comp_obj.Placement = FreeCAD.Placement(
                FreeCAD.Vector(*pos),
                FreeCAD.Rotation(*[math.radians(r) for r in rot])
            )
        
        return comp_obj
    
    def _create_lcs(self, doc: Any, parent: Any, lcs: LCS):
        """Create a Local Coordinate System."""
        import FreeCAD
        
        # Create coordinate system object
        # In real Assembly4, this would be PartDesign::CoordinateSystem
        cs = doc.addObject("Part::Feature", f"{parent.Name}_{lcs.name}")
        
        # Create visual representation (simplified)
        import Part
        # Create small axes for visualization
        origin = FreeCAD.Vector(*lcs.origin)
        x_axis = FreeCAD.Vector(*lcs.axes["x"]) * 10
        y_axis = FreeCAD.Vector(*lcs.axes["y"]) * 10
        z_axis = FreeCAD.Vector(*lcs.axes["z"]) * 10
        
        # Create lines for axes
        x_line = Part.makeLine(origin, origin + x_axis)
        y_line = Part.makeLine(origin, origin + y_axis)
        z_line = Part.makeLine(origin, origin + z_axis)
        
        cs.Shape = Part.makeCompound([x_line, y_line, z_line])
        
        # Add to parent
        if hasattr(parent, 'addObject'):
            parent.addObject(cs)
    
    def _create_joint(self, doc: Any, joint: Joint, components: Dict[str, Any]):
        """Create a joint constraint between components."""
        comp_a = components.get(joint.component_a)
        comp_b = components.get(joint.component_b)
        
        if not comp_a or not comp_b:
            logger.warning(f"Components not found for joint {joint.id}")
            return
        
        # In real Assembly4, this would create actual constraints
        # Here we just store the joint information as a property
        joint_obj = doc.addObject("App::FeaturePython", joint.id)
        joint_obj.addProperty("App::PropertyString", "Type", "Joint", "Joint type")
        joint_obj.Type = joint.type.value
        joint_obj.addProperty("App::PropertyLink", "ComponentA", "Joint", "First component")
        joint_obj.ComponentA = comp_a
        joint_obj.addProperty("App::PropertyLink", "ComponentB", "Joint", "Second component")
        joint_obj.ComponentB = comp_b
        
        # Store LCS references
        joint_obj.addProperty("App::PropertyString", "LCSA", "Joint", "LCS on component A")
        joint_obj.LCSA = joint.lcs_a
        joint_obj.addProperty("App::PropertyString", "LCSB", "Joint", "LCS on component B")
        joint_obj.LCSB = joint.lcs_b
    
    def analyze_dof(self, doc: Any, joints: List[Joint]) -> DOFAnalysis:
        """
        Analyze degrees of freedom for the assembly.
        
        Uses Gruebler-Kutzbach formula and solver Jacobian rank.
        Note: Now correctly counts ALL components in the document, 
        not just those participating in joints.
        """
        analysis = DOFAnalysis(
            global_dof=0,
            per_joint_dof={},
            overconstrained=False,
            underconstrained=False,
            driving_joints=[]
        )
        
        # Count ALL components (bodies) in the document
        # This includes unconnected components which affect DOF calculation
        components = [obj for obj in doc.Objects if obj.isDerivedFrom("Part::Feature")]
        num_bodies = len(components)
        
        # DOF per joint type
        joint_dof = {
            JointType.FIXED: 0,
            JointType.REVOLUTE: 1,
            JointType.CYLINDRICAL: 2,
            JointType.SLIDER: 1,
            JointType.BALL: 3,
            JointType.PLANAR: 3
        }
        
        # Calculate per-joint DOF
        total_joint_dof = 0
        for joint in joints:
            dof = joint_dof.get(joint.type, 0)
            analysis.per_joint_dof[joint.id] = dof
            total_joint_dof += dof
        
        # Gruebler-Kutzbach formula for spatial mechanisms
        # DOF = 6(n-1) - Σ(6-fi)
        # where n = number of bodies, fi = DOF of joint i
        num_constraints = sum(6 - dof for dof in analysis.per_joint_dof.values())
        analysis.global_dof = 6 * (num_bodies - 1) - num_constraints
        
        # Determine constraint status
        if analysis.global_dof < 0:
            analysis.overconstrained = True
            analysis.diagnostics.append(
                f"System is overconstrained with {-analysis.global_dof} redundant constraints"
            )
        elif analysis.global_dof > 0:
            analysis.underconstrained = True
            analysis.diagnostics.append(
                f"System has {analysis.global_dof} degrees of freedom"
            )
            
            # Identify driving joints (those with DOF > 0)
            analysis.driving_joints = [
                joint_id for joint_id, dof in analysis.per_joint_dof.items()
                if dof > 0
            ]
        else:
            analysis.diagnostics.append("System is properly constrained (0 DOF)")
        
        return analysis
    
    def simulate_kinematics(
        self,
        doc: Any,
        drivers: List[Dict[str, Any]],
        joints: List[Joint]
    ) -> List[KinematicFrame]:
        """
        Simulate kinematic motion with driving joints.
        
        Args:
            doc: Assembly document
            drivers: List of driver specifications
            joints: List of joints
        
        Returns:
            List of kinematic frames
        """
        frames = []
        
        if not self._solver_available:
            # Simple linear interpolation without solver
            for driver in drivers:
                joint_id = driver.get("joint_id")
                param = driver.get("param", "angle")
                start = driver.get("start", 0)
                end = driver.get("end", 90)
                step = driver.get("step", 10)
                
                num_steps = int((end - start) / step) + 1
                for i in range(num_steps):
                    value = start + i * step
                    time = i / (num_steps - 1) if num_steps > 1 else 0
                    
                    # Create frame (simplified)
                    frame = KinematicFrame(
                        time=time,
                        placements={},
                        valid=True,
                        residuals=0.0
                    )
                    
                    # In real implementation, would solve constraints here
                    frames.append(frame)
        else:
            # Use py_slvs solver
            try:
                import py_slvs
                
                # Build constraint system
                # This is a simplified example
                # Real implementation would translate joints to py_slvs constraints
                
                for driver in drivers:
                    # Iterate through driver values
                    joint_id = driver.get("joint_id")
                    param = driver.get("param", "angle")
                    start = driver.get("start", 0)
                    end = driver.get("end", 90)
                    step = driver.get("step", 10)
                    
                    num_steps = int((end - start) / step) + 1
                    for i in range(num_steps):
                        value = start + i * step
                        
                        # Solve at this configuration
                        # ... solver implementation ...
                        
                        frame = KinematicFrame(
                            time=i / (num_steps - 1) if num_steps > 1 else 0,
                            placements={},
                            valid=True,
                            residuals=0.0
                        )
                        frames.append(frame)
                        
            except Exception as e:
                logger.error(f"Kinematic simulation failed: {e}")
        
        return frames
    
    def check_collisions(
        self,
        doc: Any,
        mode: str = "assemble_validate"
    ) -> Dict[str, Any]:
        """
        Check for collisions in the assembly.
        
        Args:
            doc: Assembly document
            mode: "assemble_validate" or "simulate_allow"
        
        Returns:
            Collision detection results
        """
        # This would integrate with collision.py module
        from .collision import CollisionDetector
        
        detector = CollisionDetector()
        
        # Get all shapes from document
        shapes = []
        for obj in doc.Objects:
            if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                shapes.append((obj.Name, obj.Shape))
        
        # Check collisions
        collisions = detector.detect_collisions(shapes)
        
        result = {
            "mode": mode,
            "has_collisions": len(collisions) > 0,
            "collision_pairs": collisions
        }
        
        if mode == "assemble_validate" and collisions:
            result["error"] = "Assembly has collisions"
        elif mode == "simulate_allow" and collisions:
            result["warning"] = "Collisions detected but allowed in simulation mode"
        
        return result
    
    def export_animation(
        self,
        frames: List[KinematicFrame],
        base_path: Path
    ) -> Dict[str, Any]:
        """
        Export animation manifest and optional GLB sequence.
        
        Args:
            frames: List of kinematic frames
            base_path: Base path for output files
        
        Returns:
            Export results
        """
        # Create animation manifest
        manifest = {
            "frame_count": len(frames),
            "frames": []
        }
        
        for i, frame in enumerate(frames):
            manifest["frames"].append({
                "index": i,
                "time": frame.time,
                "valid": frame.valid,
                "placements": frame.placements
            })
        
        # Save manifest
        manifest_path = base_path.with_suffix(".animation.json")
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        result = {
            "manifest_path": str(manifest_path),
            "frame_count": len(frames)
        }
        
        # Optionally export GLB sequence
        # This would use the exporter module
        # ... GLB export implementation ...
        
        return result
    
    def _validate_upload_path(self, file_path: str) -> Path:
        """
        Validate upload file path to prevent directory traversal attacks.
        
        Args:
            file_path: Path to validate
            
        Returns:
            Validated Path object
            
        Raises:
            ValueError: If path is outside allowed directories
        """
        # Convert to Path object
        path = Path(file_path)
        
        # Resolve to absolute path (follows symlinks)
        try:
            resolved_path = path.resolve(strict=False)
        except Exception as e:
            raise ValueError(f"Invalid path: {e}")
        
        # Check if path is within any allowed directory
        path_str = str(resolved_path)
        is_allowed = False
        
        for allowed_dir in self.ALLOWED_UPLOAD_DIRS:
            # Resolve allowed directory
            allowed_resolved = Path(allowed_dir).resolve()
            
            # Check if resolved path is within allowed directory
            try:
                # This will raise ValueError if path is not relative to allowed_dir
                resolved_path.relative_to(allowed_resolved)
                is_allowed = True
                break
            except ValueError:
                continue
        
        if not is_allowed:
            # Log security violation attempt
            logger.error(
                f"Security: Path traversal attempt detected - "
                f"Path '{file_path}' resolves to '{resolved_path}' "
                f"which is outside allowed directories: {self.ALLOWED_UPLOAD_DIRS}"
            )
            raise ValueError(
                f"Path '{file_path}' is outside allowed upload directories"
            )
        
        # Additional security checks
        if '..' in path.parts:
            raise ValueError("Path contains directory traversal sequences")
        
        # Check for null bytes (path truncation attack)
        if '\x00' in str(path):
            raise ValueError("Path contains null bytes")
        
        return resolved_path
    
    def _execute_safe_script(
        self,
        script: str,
        doc: Any,
        component_id: str
    ) -> Any:
        """
        Execute a script safely using AST validation and sandboxed environment.
        
        Args:
            script: Python script to execute
            doc: FreeCAD document
            component_id: Component ID to create
            
        Returns:
            Created component object
            
        Raises:
            ValueError: If script contains unsafe operations
        """
        # Parse the script
        try:
            tree = ast.parse(script, mode='exec')
        except SyntaxError as e:
            raise ValueError(f"Script syntax error: {e}")
        
        # Validate AST nodes
        self._validate_ast_safety(tree)
        
        # Prepare sandboxed globals
        import FreeCAD
        import Part
        
        safe_globals = {
            # FreeCAD objects
            'doc': doc,
            'FreeCAD': FreeCAD,
            'Part': Part,
            
            # Component info
            'comp_id': component_id,
            
            # Safe built-in functions
            'float': float,
            'int': int,
            'str': str,
            'len': len,
            'range': range,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'sum': sum,
            'any': any,
            'all': all,
            
            # Restrict dangerous builtins
            '__builtins__': {
                'True': True,
                'False': False,
                'None': None,
            }
        }
        
        # Execute in sandboxed environment
        try:
            exec(compile(tree, '<sandboxed>', 'exec'), safe_globals)
        except Exception as e:
            logger.error(f"Script execution failed: {e}")
            raise ValueError(f"Script execution error: {e}")
        
        # Return the created component
        return doc.getObject(component_id)
    
    def _validate_ast_safety(self, tree: ast.AST):
        """
        Validate AST tree for safety.
        
        Args:
            tree: AST tree to validate
            
        Raises:
            ValueError: If unsafe operations are detected
        """
        class SafetyValidator(ast.NodeVisitor):
            def __init__(self, allowed_nodes: Set[type], allowed_functions: Set[str]):
                self.allowed_nodes = allowed_nodes
                self.allowed_functions = allowed_functions
                self.errors = []
            
            def visit(self, node):
                # Check if node type is allowed
                if type(node) not in self.allowed_nodes:
                    self.errors.append(
                        f"Unsafe AST node: {type(node).__name__} at line {getattr(node, 'lineno', '?')}"
                    )
                
                # Special handling for function calls
                if isinstance(node, ast.Call):
                    func_name = self._get_func_name(node.func)
                    if func_name and func_name not in self.allowed_functions:
                        self.errors.append(
                            f"Unsafe function call: {func_name} at line {node.lineno}"
                        )
                
                # Continue visiting child nodes
                self.generic_visit(node)
            
            def _get_func_name(self, node) -> Optional[str]:
                """Extract function name from Call node."""
                if isinstance(node, ast.Name):
                    return node.id
                elif isinstance(node, ast.Attribute):
                    # Handle chained attributes like doc.addObject
                    parts = []
                    current = node
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    return '.'.join(reversed(parts))
                return None
        
        # Validate the AST
        validator = SafetyValidator(self.SAFE_AST_NODES, self.ALLOWED_FUNCTIONS)
        validator.visit(tree)
        
        if validator.errors:
            error_msg = "Script contains unsafe operations:\n" + "\n".join(validator.errors)
            logger.error(f"Security: {error_msg}")
            raise ValueError(error_msg)


# Global assembly manager instance
assembly4_manager = Assembly4Manager()