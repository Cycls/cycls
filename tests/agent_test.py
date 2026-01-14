import pytest
import cycls
from cycls.agent import Agent, _resolve_theme
import asyncio

# To run these tests:
# poetry run pytest tests/agent_test.py -v -s


# --- Test Case 1: Basic Decorator ---
# Verifies that @cycls.agent returns an Agent instance

def test_agent_decorator_returns_agent():
    """Tests that @cycls.agent decorator returns an Agent."""
    print("\n--- Running test: test_agent_decorator_returns_agent ---")

    @cycls.agent()
    async def my_agent(context):
        yield "hello"

    assert isinstance(my_agent, Agent)
    assert my_agent.name == "my-agent"  # underscores converted to dashes
    print("✅ Test passed.")


# --- Test Case 2: Custom Name ---
# Verifies that custom name parameter works

def test_agent_custom_name():
    """Tests that custom name parameter is respected."""
    print("\n--- Running test: test_agent_custom_name ---")

    @cycls.agent(name="custom-name")
    async def my_agent(context):
        yield "hello"

    assert my_agent.name == "custom-name"
    print("✅ Test passed.")


# --- Test Case 3: Plan cycls_pass Sets Auth and Analytics ---
# Verifies that plan="cycls_pass" enables auth and analytics

def test_plan_cycls_pass_enables_auth_analytics():
    """Tests that plan='cycls_pass' sets auth=True and analytics=True."""
    print("\n--- Running test: test_plan_cycls_pass_enables_auth_analytics ---")

    @cycls.agent(plan="cycls_pass")
    async def premium_agent(context):
        yield "premium"

    assert premium_agent.config.auth == True
    assert premium_agent.config.analytics == True
    assert premium_agent.config.plan == "cycls_pass"
    print("✅ Test passed.")


# --- Test Case 4: Default Config Values ---
# Verifies default configuration values

def test_agent_default_config():
    """Tests default configuration values."""
    print("\n--- Running test: test_agent_default_config ---")

    @cycls.agent()
    async def default_agent(context):
        yield "default"

    assert default_agent.config.auth == False
    assert default_agent.config.analytics == False
    assert default_agent.config.plan == "free"
    assert default_agent.config.header == ""
    assert default_agent.config.intro == ""
    assert default_agent.config.title == ""
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


# --- Test Case 7: Agent is Callable ---
# Verifies that the decorated function can still be called

def test_agent_is_callable():
    """Tests that Agent delegates calls to the wrapped function."""
    print("\n--- Running test: test_agent_is_callable ---")

    @cycls.agent()
    def simple_agent(context):
        yield f"received: {context}"

    result = list(simple_agent("test-context"))
    assert result == ["received: test-context"]
    print("✅ Test passed.")


# --- Test Case 8: Async Function Support ---
# Verifies that async functions work correctly

def test_agent_async_function():
    """Tests that async functions work with @cycls.agent."""
    print("\n--- Running test: test_agent_async_function ---")

    @cycls.agent()
    async def async_agent(context):
        yield "async "
        yield "response"

    async def run_test():
        results = []
        async for item in async_agent("ctx"):
            results.append(item)
        return results

    results = asyncio.run(run_test())
    assert results == ["async ", "response"]
    print("✅ Test passed.")


# --- Test Case 9: Sync Function Support ---
# Verifies that sync generator functions work

def test_agent_sync_function():
    """Tests that sync generator functions work with @cycls.agent."""
    print("\n--- Running test: test_agent_sync_function ---")

    @cycls.agent()
    def sync_agent(context):
        yield "sync "
        yield "response"

    results = list(sync_agent("ctx"))
    assert results == ["sync ", "response"]
    print("✅ Test passed.")


# --- Test Case 10: Theme Resolution ---
# Verifies that theme parameter works

def test_agent_theme_resolution():
    """Tests that theme parameter is resolved correctly."""
    print("\n--- Running test: test_agent_theme_resolution ---")

    @cycls.agent(theme="dev")
    async def dev_agent(context):
        yield "dev"

    # Theme should be resolved to a path
    assert "dev-theme" in str(dev_agent.theme)
    print("✅ Test passed.")


# --- Test Case 11: Invalid Theme Raises Error ---
# Verifies that invalid theme raises ValueError

def test_agent_invalid_theme_raises():
    """Tests that invalid theme raises ValueError."""
    print("\n--- Running test: test_agent_invalid_theme_raises ---")

    with pytest.raises(ValueError, match="Unknown theme"):
        @cycls.agent(theme="nonexistent")
        async def bad_agent(context):
            yield "bad"

    print("✅ Test passed.")


# --- Test Case 12: Pip Packages Stored ---
# Verifies that pip packages are stored in agent

def test_agent_pip_packages():
    """Tests that pip packages are stored correctly."""
    print("\n--- Running test: test_agent_pip_packages ---")

    @cycls.agent(pip=["numpy", "pandas"])
    async def data_agent(context):
        yield "data"

    assert "numpy" in data_agent.pip_packages
    assert "pandas" in data_agent.pip_packages
    print("✅ Test passed.")


# --- Test Case 13: Copy and Copy Public ---
# Verifies that copy parameters are stored

def test_agent_copy_params():
    """Tests that copy and copy_public are stored correctly."""
    print("\n--- Running test: test_agent_copy_params ---")

    @cycls.agent(copy=["utils.py"], copy_public=["logo.png"])
    async def file_agent(context):
        yield "files"

    assert "utils.py" in file_agent.copy  # copy dict includes user files
    assert file_agent.copy_public == ["logo.png"]
    print("✅ Test passed.")


# --- Test Case 14: All Config Options ---
# Verifies that all config options are passed through

def test_agent_all_config_options():
    """Tests that all config options are passed through correctly."""
    print("\n--- Running test: test_agent_all_config_options ---")

    @cycls.agent(
        header="Welcome",
        intro="How can I help?",
        title="My Agent",
        auth=True,
        analytics=True,
        org="my-org"
    )
    async def full_agent(context):
        yield "full"

    assert full_agent.config.header == "Welcome"
    assert full_agent.config.intro == "How can I help?"
    assert full_agent.config.title == "My Agent"
    assert full_agent.config.auth == True
    assert full_agent.config.analytics == True
    assert full_agent.config.org == "my-org"
    print("✅ Test passed.")
