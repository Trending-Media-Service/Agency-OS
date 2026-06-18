import os
import sys
import importlib
import pytest

def clean_imports():
    """Clear sys.modules to force python to re-execute module-level code on import."""
    for mod in ["app.main", "app.database"]:
        if mod in sys.modules:
            del sys.modules[mod]

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Ensure we clean up sys.modules after each test so we don't pollute other tests."""
    yield
    clean_imports()

def test_prod_boot_guards_operator_token(monkeypatch):
    # Case 1: ENV=production + OPERATOR_TOKEN=default-dev-token -> RuntimeError
    # We must set DATABASE_URL to a non-localhost URL and WHATSAPP_APP_SECRET so that other guards pass!
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("OPERATOR_TOKEN", "default-dev-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@10.0.0.1:5432/agency_os")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "mock-whatsapp-secret")
    clean_imports()
    
    with pytest.raises(RuntimeError) as exc_info:
        import app.main
    assert "OPERATOR_TOKEN must be explicitly set" in str(exc_info.value)

def test_prod_boot_guards_database_url(monkeypatch):
    # Case 2: ENV=production + DATABASE_URL contains localhost -> RuntimeError
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/agency_os")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "mock-whatsapp-secret")
    clean_imports()
    
    with pytest.raises(RuntimeError) as exc_info:
        import app.database
    assert "DATABASE_URL still points at localhost" in str(exc_info.value)

def test_prod_boot_guards_valid_prod(monkeypatch):
    # Case 3: ENV=production + valid OPERATOR_TOKEN + valid DATABASE_URL -> boots fine
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("OPERATOR_TOKEN", "super-secret-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@10.0.0.1:5432/agency_os")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "mock-whatsapp-secret")
    clean_imports()
    
    try:
        import app.database
        import app.main
    except RuntimeError as e:
        pytest.fail(f"Boots failed in valid production configuration: {e}")

def test_prod_boot_guards_dev_mode(monkeypatch):
    # Case 4: ENV=dev/empty + default tokens -> boots fine
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("OPERATOR_TOKEN", "default-dev-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/agency_os")
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    clean_imports()
    
    try:
        import app.database
        import app.main
    except RuntimeError as e:
        pytest.fail(f"Boots failed in dev mode: {e}")
