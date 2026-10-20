"""Deterministic private derivative paths; no database or business access."""
import hashlib

ASSET_VERSION = 'document-assets-v1'


def directory(settings, item):
    # IDs are server generated; use a hash as defense in depth for filesystem keys.
    identifier = item.id if hasattr(item, 'id') else item
    key = hashlib.sha256(identifier.encode()).hexdigest()
    return settings.media_dir / '.documents' / key


def generation(settings, item):
    key = hashlib.sha256((item.sha256 + ':' + item.parser_version + ':' + ASSET_VERSION).encode()).hexdigest()[:32]
    return directory(settings, item) / key
