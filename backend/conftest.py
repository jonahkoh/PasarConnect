import sys
import os

# ── Module isolation for services with identical module names ─────────────────
# Both inventory/ and claim/ have modules named database, models, schemas, etc.
# This hook fires before every test and ensures the correct service path is at
# the front of sys.path for that test.

BACKEND_DIR        = os.path.dirname(os.path.abspath(__file__))
INVENTORY_PATH     = os.path.join(BACKEND_DIR, "inventory")
CLAIM_PATH         = os.path.join(BACKEND_DIR, "claim")
PAYMENT_PATH       = os.path.join(BACKEND_DIR, "payment")
PAYMENT_LOG_PATH   = os.path.join(BACKEND_DIR, "payment_log")
CLAIM_LOG_PATH     = os.path.join(BACKEND_DIR, "claim_log")
VERIFICATION_PATH  = os.path.join(BACKEND_DIR, "verification")

_SHARED_MODULES = [
    "database", "models", "schemas",
    "inventory_client", "publisher", "lock_service", "grpc_server",
    "claim_app", "payment_app", "payment_log_app", "claim_log_app",
]

def _set_service_path(service_path: str, also_include: str | None = None):
    """Flush shared module cache, then put service_path first in sys.path."""
    for mod in _SHARED_MODULES:
        sys.modules.pop(mod, None)
    # Reorder: remove all service paths then re-add in the desired order.
    for p in [
        INVENTORY_PATH,
        CLAIM_PATH,
        PAYMENT_PATH,
        PAYMENT_LOG_PATH,
        CLAIM_LOG_PATH,
        VERIFICATION_PATH,
    ]:
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, service_path)
    if also_include and also_include not in sys.path:
        sys.path.append(also_include)


def pytest_runtest_setup(item):
    """Before each test, set sys.path so the correct service modules load first."""
    fspath = str(item.fspath)
    if "test_inventory" in fspath:
        _set_service_path(INVENTORY_PATH)
    elif "test_claim" in fspath:
        _set_service_path(CLAIM_PATH, also_include=INVENTORY_PATH)
    elif "test_payment" in fspath:
        _set_service_path(PAYMENT_PATH, also_include=INVENTORY_PATH)
    elif "test_payment_log" in fspath:
        _set_service_path(PAYMENT_LOG_PATH)
    elif "test_claim_log" in fspath:
        _set_service_path(CLAIM_LOG_PATH)
