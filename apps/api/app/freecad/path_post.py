from __future__ import annotations


def export_gcode(job, out_path: str, processor_name: str):
    """FreeCAD sürümleri arasında post API farklılıklarını tolere eden katman.
    Deneme sırası: Path.Post → PathScripts.PostUtils → PathScripts.PathPostProcessor
    """
    # 1) Path.Post
    try:
        import Path  # type: ignore

        if hasattr(Path, "Post") and hasattr(Path.Post, "export"):
            Path.Post.export(job, out_path, processor_name)  # type: ignore[attr-defined]
            return out_path
    except Exception:
        pass
    # 2) PostUtils
    try:
        from PathScripts import PostUtils  # type: ignore

        PostUtils.export(job, out_path, processor_name)
        return out_path
    except Exception:
        pass
    # 3) PathPostProcessor
    try:
        from PathScripts import PathPostProcessor as PPP  # type: ignore

        pp = PPP.PostProcessorLoad(processor_name)
        gcode = pp.export(job)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(gcode)
        return out_path
    except Exception as e:  # pragma: no cover - platform dependent
        raise RuntimeError(f"Post-processor bulunamadı/başarısız: {processor_name}: {e}")
