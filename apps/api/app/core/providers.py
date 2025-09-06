"""
Error Message and Suggestion Providers Module

This module contains provider classes for error handling:
- ErrorMessageProvider: Bilingual error messages (Turkish/English)
- SuggestionProvider: Actionable suggestions for error resolution
- RemediationLinkProvider: Documentation links for error remediation
"""

from __future__ import annotations

from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .exceptions import ErrorCode

from .error_models import ErrorSuggestion, RemediationLink


class ErrorMessageProvider:
    """Provider for bilingual error messages."""
    
    @classmethod
    def get_message(cls, error_code: 'ErrorCode') -> Tuple[str, str]:
        """Get bilingual error message for error code."""
        from .exceptions import ErrorCode
        
        messages = {
            ErrorCode.AI_AMBIGUOUS: {
                "en": "The prompt is ambiguous and requires clarification.",
                "tr": "İstem belirsiz ve açıklama gerektiriyor."
            },
            ErrorCode.AI_HINT_REQUIRED: {
                "en": "Additional information is required to process this request.",
                "tr": "Bu isteği işlemek için ek bilgi gerekiyor."
            },
            ErrorCode.FC_GEOM_INVALID_SHAPE: {
                "en": "The model geometry is invalid (non-manifold or self-intersecting) and cannot be processed.",
                "tr": "Model geometrisi geçersiz (manifold değil veya kendisiyle kesişiyor) ve işlenemiyor."
            },
            ErrorCode.FC_BOOLEAN_FAILED: {
                "en": "Boolean operation failed due to invalid geometry or coplanar surfaces.",
                "tr": "Boolean işlemi geçersiz geometri veya eş düzlemli yüzeyler nedeniyle başarısız oldu."
            },
            ErrorCode.FC_FILLET_CHAMFER_FAILED: {
                "en": "Fillet/Chamfer operation failed; radius may exceed adjacent edge limits.",
                "tr": "Kordon/Pah işlemi başarısız oldu; yarıçap komşu kenar sınırlarını aşmış olabilir."
            },
            ErrorCode.FC_SKETCH_OVERCONSTRAINED: {
                "en": "Sketch is over-constrained; some constraints conflict.",
                "tr": "Eskiz aşırı kısıtlanmış; bazı kısıtlar birbiriyle çakışıyor."
            },
            ErrorCode.FC_SKETCH_UNDERCONSTRAINED: {
                "en": "Sketch is under-constrained and has degrees of freedom.",
                "tr": "Eskiz yetersiz kısıtlanmış ve serbestlik dereceleri var."
            },
            ErrorCode.FC_IMPORT_STEP_FAILED: {
                "en": "Failed to import the STEP file. The file may be corrupted or use unsupported entities.",
                "tr": "STEP dosyası içe aktarılamadı. Dosya bozuk olabilir veya desteklenmeyen varlıklar içeriyor olabilir."
            },
            ErrorCode.FC_EXPORT_STL_FAILED: {
                "en": "Failed to export STL file. The model may have invalid geometry.",
                "tr": "STL dosyası dışa aktarılamadı. Model geçersiz geometriye sahip olabilir."
            },
            ErrorCode.FC_A4_UNSOLVED: {
                "en": "Assembly constraints cannot be solved; check LCS alignment and cyclic dependencies.",
                "tr": "Montaj kısıtları çözülemedi; LCS hizalamasını ve döngüsel bağımlılıkları kontrol edin."
            },
            ErrorCode.FC_A4_LINK_SCOPE: {
                "en": "Assembly links are out of scope or LCS is missing.",
                "tr": "Montaj bağlantıları kapsam dışında veya LCS eksik."
            },
            ErrorCode.FC_MESH_FAILED: {
                "en": "Mesh generation failed due to invalid geometry or non-manifold edges.",
                "tr": "Ağ oluşturma geçersiz geometri veya manifold olmayan kenarlar nedeniyle başarısız oldu."
            },
            ErrorCode.FC_RECOMPUTE_FAILED: {
                "en": "Document recompute failed due to cyclic dependencies or invalid operations.",
                "tr": "Belge yeniden hesaplama döngüsel bağımlılıklar veya geçersiz işlemler nedeniyle başarısız oldu."
            },
            ErrorCode.FC_TOPONAMING_UNSTABLE: {
                "en": "Topological references were lost after model changes.",
                "tr": "Model değişikliklerinden sonra topolojik referanslar kayboldu."
            },
            ErrorCode.TIMEOUT_WORKER: {
                "en": "Processing timed out. The model is too complex or system is overloaded.",
                "tr": "İşleme zaman aşımına uğradı. Model çok karmaşık veya sistem aşırı yük altında."
            },
            ErrorCode.STORAGE_QUOTA_EXCEEDED: {
                "en": "Storage quota exceeded. Please free up space or upgrade your plan.",
                "tr": "Depolama kotası aşıldı. Lütfen alan boşaltın veya planınızı yükseltin."
            },
            ErrorCode.VALIDATION_RANGE_VIOLATION: {
                "en": "Value is outside the acceptable range.",
                "tr": "Değer kabul edilebilir aralığın dışında."
            },
            ErrorCode.VALIDATION_CONFLICT: {
                "en": "Conflicting parameters detected.",
                "tr": "Çakışan parametreler tespit edildi."
            },
        }
        
        message_dict = messages.get(error_code, {})
        return (
            message_dict.get("en", f"Error: {error_code.value}"),
            message_dict.get("tr", f"Hata: {error_code.value}")
        )


class SuggestionProvider:
    """Provider for actionable error suggestions."""
    
    @classmethod
    def get_suggestions(cls, error_code: 'ErrorCode') -> List[ErrorSuggestion]:
        """Get suggestions for error code."""
        from .exceptions import ErrorCode
        
        suggestions = {
            ErrorCode.FC_GEOM_INVALID_SHAPE: [
                ErrorSuggestion(
                    en="Heal geometry and remove self-intersections; ensure solids are closed/manifold.",
                    tr="Geometriyi iyileştirin ve kendi kendini kesişmeleri kaldırın; katıların kapalı/manifold olduğundan emin olun."
                ),
                ErrorSuggestion(
                    en="Use 'Refine shape' after boolean operations.",
                    tr="Boolean işlemlerden sonra 'Refine shape' kullanın."
                ),
            ],
            ErrorCode.FC_FILLET_CHAMFER_FAILED: [
                ErrorSuggestion(
                    en="Reduce fillet radius below the smallest adjacent edge length.",
                    tr="Kordon yarıçapını en küçük komşu kenar uzunluğunun altına indirin."
                ),
                ErrorSuggestion(
                    en="Increase wall thickness to accommodate larger fillets.",
                    tr="Daha büyük kordonları barındırmak için duvar kalınlığını artırın."
                ),
            ],
            ErrorCode.FC_SKETCH_OVERCONSTRAINED: [
                ErrorSuggestion(
                    en="Remove redundant constraints and apply dimensional constraints incrementally.",
                    tr="Gereksiz kısıtları kaldırın ve boyutsal kısıtları kademeli uygulayın."
                ),
                ErrorSuggestion(
                    en="Check for conflicting dimensional and geometric constraints.",
                    tr="Çakışan boyutsal ve geometrik kısıtları kontrol edin."
                ),
            ],
            ErrorCode.FC_IMPORT_STEP_FAILED: [
                ErrorSuggestion(
                    en="Export STEP as AP214/AP242 format for better compatibility.",
                    tr="Daha iyi uyumluluk için STEP'i AP214/AP242 formatında dışa aktarın."
                ),
                ErrorSuggestion(
                    en="Ensure units are set to millimeters and run a CAD repair tool before upload.",
                    tr="Birimlerin milimetre olarak ayarlandığından emin olun ve yüklemeden önce CAD onarım aracı çalıştırın."
                ),
            ],
            ErrorCode.FC_MESH_FAILED: [
                ErrorSuggestion(
                    en="Enable mesh refinement and reduce feature complexity.",
                    tr="Ağ iyileştirmeyi etkinleştirin ve özellik karmaşıklığını azaltın."
                ),
                ErrorSuggestion(
                    en="Fix non-manifold edges and ensure watertight geometry.",
                    tr="Manifold olmayan kenarları düzeltin ve su geçirmez geometri sağlayın."
                ),
            ],
            ErrorCode.FC_A4_UNSOLVED: [
                ErrorSuggestion(
                    en="Ensure each part has an LCS (Local Coordinate System).",
                    tr="Her parçanın bir LCS'si (Yerel Koordinat Sistemi) olduğundan emin olun."
                ),
                ErrorSuggestion(
                    en="Solve constraints stepwise and avoid circular dependencies.",
                    tr="Kısıtları adım adım çözün ve döngüsel bağımlılıklardan kaçının."
                ),
            ],
            ErrorCode.TIMEOUT_WORKER: [
                ErrorSuggestion(
                    en="Simplify model by reducing feature count or fillet complexity.",
                    tr="Özellik sayısını veya kordon karmaşıklığını azaltarak modeli basitleştirin."
                ),
                ErrorSuggestion(
                    en="Split complex assemblies into smaller subassemblies.",
                    tr="Karmaşık montajları daha küçük alt montajlara bölün."
                ),
            ],
            ErrorCode.VALIDATION_RANGE_VIOLATION: [
                ErrorSuggestion(
                    en="Check minimum and maximum values for this parameter.",
                    tr="Bu parametre için minimum ve maksimum değerleri kontrol edin."
                ),
                ErrorSuggestion(
                    en="Ensure values meet manufacturing constraints (e.g., minimum wall thickness >= 1.5mm).",
                    tr="Değerlerin üretim kısıtlarını karşıladığından emin olun (örn. minimum duvar kalınlığı >= 1.5mm)."
                ),
            ],
        }
        
        return suggestions.get(error_code, [])


class RemediationLinkProvider:
    """Provider for remediation documentation links."""
    
    @classmethod
    def get_links(cls, error_code: 'ErrorCode') -> List[RemediationLink]:
        """Get remediation links for error code."""
        from .exceptions import ErrorCode
        
        links = {
            ErrorCode.FC_GEOM_INVALID_SHAPE: [
                RemediationLink(
                    title="FreeCAD Geometry Cleanup",
                    url="https://wiki.freecad.org/Part_RefineShape"
                ),
                RemediationLink(
                    title="BRep Validity and Healing",
                    url="https://wiki.freecad.org/Part_Workbench"
                ),
            ],
            ErrorCode.FC_FILLET_CHAMFER_FAILED: [
                RemediationLink(
                    title="Fillet Best Practices",
                    url="https://wiki.freecad.org/PartDesign_Fillet"
                ),
            ],
            ErrorCode.FC_SKETCH_OVERCONSTRAINED: [
                RemediationLink(
                    title="Sketcher Constraints Guide",
                    url="https://wiki.freecad.org/Sketcher_Workbench"
                ),
            ],
            ErrorCode.FC_IMPORT_STEP_FAILED: [
                RemediationLink(
                    title="STEP Import Tips",
                    url="https://wiki.freecad.org/Import_Export"
                ),
            ],
            ErrorCode.FC_MESH_FAILED: [
                RemediationLink(
                    title="Mesh Best Practices",
                    url="https://wiki.freecad.org/Mesh_Workbench"
                ),
            ],
            ErrorCode.FC_A4_UNSOLVED: [
                RemediationLink(
                    title="Assembly4 Documentation",
                    url="https://wiki.freecad.org/Assembly4_Workbench"
                ),
            ],
            ErrorCode.TIMEOUT_WORKER: [
                RemediationLink(
                    title="Performance Optimization Tips",
                    url="https://wiki.freecad.org/Performance_tips"
                ),
            ],
        }
        
        return links.get(error_code, [])