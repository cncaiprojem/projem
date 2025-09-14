"""
Centralized validation messages for Task 7.24

All Turkish validation messages are consolidated here to avoid duplication
and ensure consistency across the application.
"""

from typing import Dict


VALIDATION_MESSAGES_TR: Dict[str, str] = {
    # General validation messages
    "geometry_check_failed": "Geometri kontrolü başarısız",
    "manufacturing_check_failed": "Üretim kontrolü başarısız",
    "standards_check_failed": "Standart kontrolü başarısız",
    "quality_check_failed": "Kalite kontrolü başarısız",
    "certification_check_failed": "Sertifikasyon kontrolü başarısız",
    
    # Geometry validation
    "non_manifold_edges": "Manifold olmayan kenarlar tespit edildi",
    "self_intersecting_faces": "Kendisiyle kesişen yüzeyler bulundu",
    "degenerate_faces": "Dejenere yüzeyler tespit edildi",
    "invalid_topology": "Geçersiz topoloji",
    "open_shells": "Açık kabuklar bulundu",
    "inconsistent_normals": "Tutarsız yüzey normalleri",
    "zero_volume": "Sıfır hacim tespit edildi",
    "negative_volume": "Negatif hacim tespit edildi",
    
    # Manufacturing validation
    "thin_walls": "İnce duvarlar tespit edildi",
    "sharp_corners": "Keskin köşeler bulundu",
    "undercuts": "Alt kesimler tespit edildi",
    "inaccessible_features": "Erişilemeyen özellikler bulundu",
    "tolerance_violation": "Tolerans ihlali",
    "material_incompatible": "Malzeme uyumsuzluğu",
    "exceeds_build_volume": "Yapı hacmini aşıyor",
    "overhangs": "Çıkıntılar tespit edildi",
    "trapped_volumes": "Hapsolmuş hacimler bulundu",
    "non_uniform_walls": "Düzensiz duvar kalınlığı",
    "missing_draft": "Çekme açısı eksik",
    "complex_undercuts": "Karmaşık alt kesimler",
    "varying_thickness": "Değişken kalınlık",
    "invalid_bend_radius": "Geçersiz bükme yarıçapı",
    "gating_issue": "Yolluk konumu sorunu",
    "hot_spots": "Sıcak noktalar tespit edildi",
    
    # Standards compliance
    "iso_non_compliant": "ISO standardına uygun değil",
    "asme_non_compliant": "ASME standardına uygun değil",
    "din_non_compliant": "DIN standardına uygun değil",
    "missing_tolerances": "Eksik toleranslar",
    "invalid_gdt": "Geçersiz GD&T",
    "missing_annotations": "Eksik açıklamalar",
    
    # Quality metrics
    "low_quality_score": "Düşük kalite puanı",
    "high_complexity": "Yüksek karmaşıklık",
    "poor_surface_finish": "Kötü yüzey kalitesi",
    "dimensional_deviation": "Boyutsal sapma",
    
    # File/format issues
    "invalid_file_format": "Geçersiz dosya formatı",
    "corrupted_file": "Bozuk dosya",
    "unsupported_format": "Desteklenmeyen format",
    "file_too_large": "Dosya çok büyük",
    "no_geometry": "Geometri bulunamadı",
    
    # Process-specific messages
    "cnc_validation_error": "CNC doğrulama hatası",
    "print_validation_error": "3D baskı doğrulama hatası",
    "injection_validation_error": "Enjeksiyon kalıplama doğrulama hatası",
    "sheet_metal_validation_error": "Sac metal doğrulama hatası",
    "casting_validation_error": "Döküm doğrulama hatası",
    
    # Fix suggestions
    "fix_available": "Düzeltme mevcut",
    "auto_fix_possible": "Otomatik düzeltme mümkün",
    "manual_fix_required": "Manuel düzeltme gerekli",
    "redesign_suggested": "Yeniden tasarım önerilir",
    
    # Severity descriptions
    "critical": "Kritik",
    "error": "Hata",
    "warning": "Uyarı",
    "info": "Bilgi",
    
    # Status messages
    "validation_started": "Doğrulama başladı",
    "validation_completed": "Doğrulama tamamlandı",
    "validation_failed": "Doğrulama başarısız",
    "processing": "İşleniyor",
    "queued": "Sırada",
    "cancelled": "İptal edildi",
    
    # Certificate messages
    "certificate_issued": "Sertifika düzenlendi",
    "certificate_valid": "Sertifika geçerli",
    "certificate_invalid": "Sertifika geçersiz",
    "certificate_expired": "Sertifika süresi dolmuş",
    
    # Error messages
    "internal_error": "İç hata oluştu",
    "database_error": "Veritabanı hatası",
    "file_not_found": "Dosya bulunamadı",
    "permission_denied": "Erişim reddedildi",
    "invalid_parameters": "Geçersiz parametreler",
    "operation_timeout": "İşlem zaman aşımına uğradı",
    
    # Success messages
    "operation_successful": "İşlem başarılı",
    "model_valid": "Model geçerli",
    "all_checks_passed": "Tüm kontroller başarılı",
    "ready_for_production": "Üretime hazır",
    
    # Manufacturing process names
    "cnc_milling": "CNC Frezeleme",
    "cnc_turning": "CNC Tornalama",
    "cnc_laser": "CNC Lazer",
    "cnc_plasma": "CNC Plazma",
    "fdm_3d_printing": "FDM 3D Baskı",
    "sla_3d_printing": "SLA 3D Baskı",
    "sls_3d_printing": "SLS 3D Baskı",
    "injection_molding": "Enjeksiyon Kalıplama",
    "sheet_metal": "Sac Metal",
    "casting": "Döküm",
    
    # Units and measurements
    "millimeters": "milimetre",
    "degrees": "derece",
    "seconds": "saniye",
    "minutes": "dakika",
    "hours": "saat",
    "days": "gün",
    
    # Actions
    "view_details": "Detayları Görüntüle",
    "apply_fix": "Düzeltmeyi Uygula",
    "download_report": "Raporu İndir",
    "request_certificate": "Sertifika Talep Et",
    "contact_support": "Destek ile İletişime Geç"
}


def get_message(key: str, default: str = None) -> str:
    """
    Get a Turkish validation message by key.
    
    Args:
        key: Message key
        default: Default message if key not found
    
    Returns:
        Turkish message or default
    """
    return VALIDATION_MESSAGES_TR.get(key, default or key)


def format_message(key: str, **kwargs) -> str:
    """
    Get and format a Turkish validation message with parameters.
    
    Args:
        key: Message key
        **kwargs: Format parameters
    
    Returns:
        Formatted Turkish message
    """
    message = get_message(key)
    try:
        return message.format(**kwargs)
    except KeyError:
        return message