"""CareOS-global operator surface — the one module that is not tenant-scoped.

Every other module in `careos.modules` describes something an agency owns. This one
describes CareOS itself: who operates the platform, what they can see across tenants, and
the record of them looking.

It is deliberately a separate identity (`platform_operator`) rather than a seventh `Role` on
`app_user`. See `models.py` for why, and `careos/db/rls.py` for the database roles that make
the separation structural rather than conventional.
"""
