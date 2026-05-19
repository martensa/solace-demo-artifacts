"""OpenMetadata Solace Event Portal connector.

Top-level exports are intentionally lazy: importing this package must not
pull in `openmetadata-ingestion`, so the bridge and bootstrap CLIs can
load `connector.mappers` / `connector.bootstrap` in slimmer runtime
environments. OM's workflow engine references the source class by its
fully-qualified path (`connector.event_portal_connector.SolaceEventPortalSource`)
so no re-export is needed here.
"""
__version__ = "0.2.0"
