"""
Internationalization (i18n) system for backend error messages.
Supports French (default) and Arabic with proper message keys.
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# French translations (default)
FR: dict[str, str] = {
    # Auth
    "auth.invalid_credentials": "Identifiants invalides.",
    "auth.account_disabled": "Ce compte est désactivé.",
    "auth.account_locked": "Ce compte est bloqué suite à plusieurs tentatives échouées. Réessayez dans 15 minutes.",
    "auth.token_expired": "Le jeton a expiré.",
    "auth.token_invalid": "Jeton invalide.",
    "auth.refresh_token_revoked": "Le jeton de rafraîchissement a été révoqué.",
    "auth.password_changed": "Mot de passe modifié avec succès.",
    "auth.password_mismatch": "Le mot de passe actuel est incorrect.",
    "auth.logout_success": "Déconnexion réussie.",
    "auth.too_many_attempts": "Trop de tentatives. Veuillez réessayer plus tard.",

    # Users
    "user.not_found": "Utilisateur non trouvé.",
    "user.email_exists": "Cette adresse email est déjà utilisée.",
    "user.username_exists": "Ce nom d'utilisateur est déjà utilisé.",
    "user.created": "Utilisateur créé avec succès.",
    "user.updated": "Utilisateur mis à jour avec succès.",
    "user.deleted": "Utilisateur supprimé avec succès.",

    # Vehicles
    "vehicle.not_found": "Véhicule non trouvé.",
    "vehicle.registration_exists": "Ce numéro d'immatriculation est déjà enregistré.",
    "vehicle.vin_exists": "Ce numéro de châssis (VIN) est déjà enregistré.",
    "vehicle.created": "Véhicule créé avec succès.",
    "vehicle.updated": "Véhicule mis à jour avec succès.",
    "vehicle.deleted": "Véhicule supprimé avec succès.",
    "vehicle.invalid_status_transition": "Transition de statut invalide : {from_status} → {to_status}.",
    "vehicle.mileage_decrease": "Le kilométrage ne peut pas diminuer sans autorisation administrateur.",

    # Reservations
    "reservation.not_found": "Réservation non trouvée.",
    "reservation.double_booking": "Ce véhicule est déjà réservé pendant cette période.",
    "reservation.created": "Réservation créée avec succès.",
    "reservation.cancelled": "Réservation annulée avec succès.",
    "reservation.invalid_dates": "Les dates de réservation sont invalides.",

    # Clients
    "client.not_found": "Client non trouvé.",
    "client.created": "Client créé avec succès.",
    "client.updated": "Client mis à jour avec succès.",
    "client.deleted": "Client supprimé avec succès.",

    # Sync
    "sync.conflict": "Conflit de synchronisation détecté.",
    "sync.push_success": "Synchronisation envoyée avec succès.",
    "sync.pull_success": "Synchronisation reçue avec succès.",
    "sync.idempotency_duplicate": "Opération déjà traitée.",

    # General
    "permission.denied": "Accès refusé.",
    "validation.error": "Erreur de validation.",
    "server.error": "Erreur interne du serveur.",
    "rate_limit.exceeded": "Limite de requêtes dépassée. Réessayez plus tard.",
}

# Arabic translations
AR: dict[str, str] = {
    # Auth
    "auth.invalid_credentials": "بيانات الاعتماد غير صالحة.",
    "auth.account_disabled": "هذا الحساب معطل.",
    "auth.account_locked": "تم قفل هذا الحساب بسبب عدة محاولات فاشلة. يرجى المحاولة بعد 15 دقيقة.",
    "auth.token_expired": "انتهت صلاحية الرمز.",
    "auth.token_invalid": "رمز غير صالح.",
    "auth.refresh_token_revoked": "تم إلغاء رمز التحديث.",
    "auth.password_changed": "تم تغيير كلمة المرور بنجاح.",
    "auth.password_mismatch": "كلمة المرور الحالية غير صحيحة.",
    "auth.logout_success": "تم تسجيل الخروج بنجاح.",
    "auth.too_many_attempts": "محاولات كثيرة جداً. يرجى المحاولة لاحقاً.",

    # Users
    "user.not_found": "المستخدم غير موجود.",
    "user.email_exists": "هذا البريد الإلكتروني مستخدم بالفعل.",
    "user.username_exists": "اسم المستخدم هذا مستخدم بالفعل.",
    "user.created": "تم إنشاء المستخدم بنجاح.",
    "user.updated": "تم تحديث المستخدم بنجاح.",
    "user.deleted": "تم حذف المستخدم بنجاح.",

    # Vehicles
    "vehicle.not_found": "المركبة غير موجودة.",
    "vehicle.registration_exists": "رقم التسجيل هذا مسجل بالفعل.",
    "vehicle.vin_exists": "رقم الهيكل (VIN) هذا مسجل بالفعل.",
    "vehicle.created": "تم إنشاء المركبة بنجاح.",
    "vehicle.updated": "تم تحديث المركبة بنجاح.",
    "vehicle.deleted": "تم حذف المركبة بنجاح.",
    "vehicle.invalid_status_transition": "انتقال حالة غير صالح: {from_status} → {to_status}.",
    "vehicle.mileage_decrease": "لا يمكن تقليل عداد المسافات بدون إذن المسؤول.",

    # Reservations
    "reservation.not_found": "الحجز غير موجود.",
    "reservation.double_booking": "هذه السيارة محجوزة بالفعل خلال هذه الفترة.",
    "reservation.created": "تم إنشاء الحجز بنجاح.",
    "reservation.cancelled": "تم إلغاء الحجز بنجاح.",
    "reservation.invalid_dates": "تواريخ الحجز غير صالحة.",

    # Clients
    "client.not_found": "العميل غير موجود.",
    "client.created": "تم إنشاء العميل بنجاح.",
    "client.updated": "تم تحديث العميل بنجاح.",
    "client.deleted": "تم حذف العميل بنجاح.",

    # Sync
    "sync.conflict": "تم اكتشاف تعارض في المزامنة.",
    "sync.push_success": "تمت المزامنة بنجاح.",
    "sync.pull_success": "تم استلام المزامنة بنجاح.",
    "sync.idempotency_duplicate": "تمت معالجة العملية بالفعل.",

    # General
    "permission.denied": "تم رفض الوصول.",
    "validation.error": "خطأ في التحقق.",
    "server.error": "خطأ داخلي في الخادم.",
    "rate_limit.exceeded": "تم تجاوز حد الطلبات. حاول مرة أخرى لاحقاً.",
}

# Language registry
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "fr": FR,
    "ar": AR,
}

DEFAULT_LANGUAGE = "fr"


def get_message(
    key: str,
    lang: Optional[str] = None,
    **kwargs,
) -> str:
    """
    Get a localized message by key.
    Falls back to French if key not found in requested language.
    """
    language = lang or DEFAULT_LANGUAGE
    translations = _TRANSLATIONS.get(language, _TRANSLATIONS[DEFAULT_LANGUAGE])
    message = translations.get(key)

    if message is None:
        # Fallback to French
        message = _TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)

    # Format with kwargs if provided
    if kwargs:
        try:
            message = message.format(**kwargs)
        except (KeyError, ValueError):
            pass

    return message
