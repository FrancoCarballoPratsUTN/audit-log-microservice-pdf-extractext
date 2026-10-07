"""Capa 3 - Acceso a datos.

Implementación del puerto `AuditLogRepository` sobre MongoDB: cliente,
índices, escritura y traducción de errores del driver.

No importa nada de `app.api` ni de `app.services`: la dependencia apunta hacia
adentro, y el cableado ocurre en el composition root (`app/main.py`). Esa
restricción la verifica `tests/unit/test_package_layout.py`.
"""
