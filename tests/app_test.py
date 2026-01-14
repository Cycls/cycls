import pytest
import cycls
from cycls.app import App
import asyncio

# To run these tests:
# poetry run pytest tests/app_test.py -v -s


# --- Test Case 1: Basic Decorator ---
# Verifies that @cycls.app returns an App instance

def test_app_decorator_returns_app():
    """Tests that @cycls.app decorator returns an App."""
    print("\n--- Running test: test_app_decorator_returns_app ---")

    @cycls.app()
    async def my_app(context):
        yield "hello"

    assert isinstance(my_app, App)
    assert my_app.name == "my-app"  # underscores converted to dashes
    print("✅ Test passed.")


# --- Test Case 2: Custom Name ---
# Verifies that custom name parameter works

def test_app_custom_name():
    """Tests that custom name parameter is respected."""
    print("\n--- Running test: test_app_custom_name ---")

    @cycls.app(name="custom-name")
    async def my_app(context):
        yield "hello"

    assert my_app.name == "custom-name"
    print("✅ Test passed.")


# --- Test Case 3: Plan cycls_pass Sets Auth and Analytics ---
# Verifies that plan="cycls_pass" enables auth and analytics

def test_plan_cycls_pass_enables_auth_analytics():
    """Tests that plan='cycls_pass' sets auth=True and analytics=True."""
    print("\n--- Running test: test_plan_cycls_pass_enables_auth_analytics ---")

    @cycls.app(plan="cycls_pass")
    async def premium_app(context):
        yield "premium"

    assert premium_app.config.auth == True
    assert premium_app.config.analytics == True
    assert premium_app.config.plan == "cycls_pass"
    print("✅ Test passed.")


# --- Test Case 4: Default Config Values ---
# Verifies default configuration values

def test_app_default_config():
    """Tests default configuration values."""
    print("\n--- Running test: test_app_default_config ---")

    @cycls.app()
    async def default_app(context):
        yield "default"

    assert default_app.config.auth == False
    assert default_app.config.analytics == False
    assert default_app.config.plan == "free"
    assert default_app.config.header == ""
    assert default_app.config.intro == ""
    assert default_app.config.title == ""
    print("✅ Test passed.")


# --- Test Case 5: Module-Level API Key ---
# Verifies that cycls.api_key can be set and read

def test_module_level_api_key():
    """Tests module-level api_key configuration."""
    print("\n--- Running test: test_module_level_api_key ---")

    original = cycls.api_key

    cycls.api_key = "test-key-123"
    assert cycls.api_key == "test-key-123"

    # Restore original
    cycls.api_key = original
    print("✅ Test passed.")


# --- Test Case 6: Module-Level Base URL ---
# Verifies that cycls.base_url can be set and read

def test_module_level_base_url():
    """Tests module-level base_url configuration."""
    print("\n--- Running test: test_module_level_base_url ---")

    original = cycls.base_url

    cycls.base_url = "https://custom.api.com"
    assert cycls.base_url == "https://custom.api.com"

    # Restore original
    cycls.base_url = original
    print("✅ Test passed.")


# --- Test Case 7: App is Callable ---
# Verifies that the decorated function can still be called

def test_app_is_callable():
    """Tests that App delegates calls to the wrapped function."""
    print("\n--- Running test: test_app_is_callable ---")

    @cycls.app()
    def simple_app(context):
        yield f"received: {context}"

    result = list(simple_app("test-context"))
    assert result == ["received: test-context"]
    print("✅ Test passed.")


# --- Test Case 8: Async Function Support ---
# Verifies that async functions work correctly

def test_app_async_function():
    """Tests that async functions work with @cycls.app."""
    print("\n--- Running test: test_app_async_function ---")

    @cycls.app()
    async def async_app(context):
        yield "async "
        yield "response"

    async def run_test():
        results = []
        async for item in async_app("ctx"):
            results.append(item)
        return results

    results = asyncio.run(run_test())
    assert results == ["async ", "response"]
    print("✅ Test passed.")


# --- Test Case 9: Sync Function Support ---
# Verifies that sync generator functions work

def test_app_sync_function():
    """Tests that sync generator functions work with @cycls.app."""
    print("\n--- Running test: test_app_sync_function ---")

    @cycls.app()
    def sync_app(context):
        yield "sync "
        yield "response"

    results = list(sync_app("ctx"))
    assert results == ["sync ", "response"]
    print("✅ Test passed.")


# --- Test Case 10: Theme Resolution ---
# Verifies that theme parameter works

def test_app_theme_resolution():
    """Tests that theme parameter is stored correctly."""
    print("\n--- Running test: test_app_theme_resolution ---")

    @cycls.app(theme="dev")
    async def dev_app(context):
        yield "dev"

    assert dev_app.theme == "dev"
    print("✅ Test passed.")


# --- Test Case 11: Invalid Theme Raises Error ---
# Verifies that invalid theme raises ValueError

def test_app_invalid_theme_raises():
    """Tests that invalid theme raises ValueError."""
    print("\n--- Running test: test_app_invalid_theme_raises ---")

    with pytest.raises(ValueError, match="Unknown theme"):
        @cycls.app(theme="nonexistent")
        async def bad_app(context):
            yield "bad"

    print("✅ Test passed.")


# --- Test Case 12: Pip Packages Stored ---
# Verifies that pip packages are stored in agent

def test_app_pip():
    """Tests that pip packages are stored correctly."""
    print("\n--- Running test: test_app_pip ---")

    @cycls.app(pip=["numpy", "pandas"])
    async def data_app(context):
        yield "data"

    assert "numpy" in data_app.pip
    assert "pandas" in data_app.pip
    print("✅ Test passed.")


# --- Test Case 13: Copy and Copy Public ---
# Verifies that copy parameters are stored

def test_app_copy_params():
    """Tests that copy and copy_public are stored correctly."""
    print("\n--- Running test: test_app_copy_params ---")

    @cycls.app(copy=["utils.py"], copy_public=["logo.png"])
    async def file_app(context):
        yield "files"

    assert "utils.py" in file_app.copy  # copy dict includes user files
    assert file_app.copy_public == ["logo.png"]
    print("✅ Test passed.")


# --- Test Case 14: All Config Options ---
# Verifies that all config options are passed through

def test_app_all_config_options():
    """Tests that all config options are passed through correctly."""
    print("\n--- Running test: test_app_all_config_options ---")

    @cycls.app(
        header="Welcome",
        intro="How can I help?",
        title="My App",
        auth=True,
        analytics=True,
        org="my-org"
    )
    async def full_app(context):
        yield "full"

    assert full_app.config.header == "Welcome"
    assert full_app.config.intro == "How can I help?"
    assert full_app.config.title == "My App"
    assert full_app.config.auth == True
    assert full_app.config.analytics == True
    assert full_app.config.org == "my-org"
    print("✅ Test passed.")
