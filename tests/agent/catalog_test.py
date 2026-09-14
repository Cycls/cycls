"""examples/agent/catalog.py — the connector catalog a deploy file imports.

Constructing it is the test: `Connector.__init__` validates scope and the api base, `OAuth2.__init__`
wants authorize/token/client_id unless it discovers them, and today those raise only on deploy. This
puts them on `pytest tests/`. It also pins the two rules the catalog exists to keep: every declaration
reaches `ALL`, and nothing in the module is a callable cloudpickle would pickle by reference.
"""
import sys
import pytest
from cycls._agent.connectors import Connector

@pytest.fixture(scope="module")
def catalog():
    sys.path.insert(0, "examples/agent")
    try:
        import catalog as mod
    finally:
        sys.path.pop(0)
    return mod


def test_every_declaration_constructs(catalog):
    """Every connector and its servers, built. A bad scope or a non-https api base raises here."""
    assert [o.name for o in catalog.ALL] == \
        ["google", "gmail", "gcal", "posthog", "salla", "notion", "apify", "zid", "github", "hubspot", "slack"]
    assert all(isinstance(o, Connector) for o in catalog.ALL)


def test_every_server_belongs_to_a_listed_connector(catalog):
    """A server wired to a connector the directory never offers is a tool nobody can connect."""
    listed = {o.name for o in catalog.ALL}
    for s in [*catalog.SERVERS, catalog.posthog_mcp]:
        assert s._connector is not None and s._connector.name in listed, s.label


def test_server_labels_are_unique(catalog):
    """Tools are prefixed `{label}_`, so two servers sharing one label collide in the tool list."""
    labels = [s.label for s in [*catalog.SERVERS, catalog.posthog_mcp]]
    assert len(labels) == len(set(labels)), labels


def test_secrets_are_env_references_never_literals(catalog):
    """The catalog is tracked; a client secret in it would be a secret in git."""
    from cycls._agent.connectors import Env
    for o in catalog.ALL:
        for field in (getattr(o, "client_id", None), getattr(o, "secret", None)):
            assert field is None or isinstance(field, Env), o.name


def test_the_catalog_holds_no_callable(catalog):
    """cloudpickle pickles a function from an imported module by reference, so a lambda declared here
    boots the container into `import catalog` — an ImportError on a machine that has no such file.
    Classifiers and handlers belong in the deploy file, where they are `__main__`."""
    bad = [n for n, v in vars(catalog).items()
           if not n.startswith("__") and callable(v) and getattr(v, "__module__", None) == "catalog"]
    assert bad == [], f"move these into the deploy file: {bad}"
