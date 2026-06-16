"""Corporate TLS bootstrap.

On networks with a TLS-intercepting proxy, the proxy presents its own
certificate. The OS (Windows) trust store has the corporate root CA, but
Python's bundled `certifi` store does not — so the Google / OpenAI SDKs raise
``SSL: CERTIFICATE_VERIFY_FAILED``.

Fix without touching IT or adding a dependency: export the OS root store to a
PEM bundle (see README/INSTALL) and point Python's TLS stack at it. This module
sets the relevant env vars (httpx/requests use SSL_CERT_FILE / REQUESTS_CA_BUNDLE;
grpc uses GRPC_DEFAULT_SSL_ROOTS_FILE_PATH) from one bundle.

It's a no-op when no bundle is present, so machines without an intercepting
proxy (CI, cloud) are unaffected.
"""

import os
from pathlib import Path

# Repo-local default produced by the export step. Override with CORP_CA_BUNDLE.
_DEFAULT_BUNDLE = Path(__file__).resolve().parents[2] / "certs" / "corp-ca-bundle.pem"

_TLS_ENV_VARS = (
    "SSL_CERT_FILE",            # Python ssl / httpx default context
    "REQUESTS_CA_BUNDLE",       # requests
    "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",  # grpc (google-genai transport)
)


def configure_corporate_tls() -> str | None:
    """Point Python's TLS at the corporate CA bundle if one is available.

    Resolution order: ``CORP_CA_BUNDLE`` env var, else the repo-local
    ``certs/corp-ca-bundle.pem``. Existing TLS env vars are respected (we only
    fill in ones that aren't already set). Returns the bundle path used, or None.
    """
    bundle = os.environ.get("CORP_CA_BUNDLE")
    if not bundle and _DEFAULT_BUNDLE.exists():
        bundle = str(_DEFAULT_BUNDLE)
    if not bundle:
        return None

    bundle = str(Path(bundle).resolve())
    for var in _TLS_ENV_VARS:
        os.environ.setdefault(var, bundle)
    return bundle
