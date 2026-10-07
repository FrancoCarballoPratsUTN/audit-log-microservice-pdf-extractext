"""Tests de integración.

Cruzan un límite (HTTP, base de datos). Requieren `mongod` alcanzable vía
`MONGO_URI`; sin él, esa parte de la suite no corre y el checkpoint lo declara
en vez de marcarse verde.
"""
