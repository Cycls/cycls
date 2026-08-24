"""Tests for AppleIAP per-product plans: dict-form mapping + legacy set-form."""
import time
import uuid

from cycls._app.auth import AppleIAP, User

NAMESPACE = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
BUNDLE = "com.cycls.app"
PRO = "com.cycls.app.pro.month"
MAX = "com.cycls.app.max.month"


def _iap(products, monkeypatch, payloads):
    """An AppleIAP whose _decode returns the payload keyed by the jws string."""
    iap = AppleIAP(bundle_id=BUNDLE, products=products, namespace=NAMESPACE,
                   root_cert=b"unused")
    monkeypatch.setattr(iap, "_decode", lambda jws: payloads[jws])
    return iap


def _payload(product_id, user_id, **overrides):
    return {
        "bundleId": BUNDLE,
        "productId": product_id,
        "appAccountToken": str(uuid.uuid5(uuid.UUID(NAMESPACE), user_id)),
        "expiresDate": (time.time() + 3600) * 1000,
        "revocationDate": None,
        **overrides,
    }


def test_dict_form_grants_plan_per_product(monkeypatch):
    iap = _iap({PRO: "u:ios_pro", MAX: "u:ios_max"}, monkeypatch, {
        "pro-jws": _payload(PRO, "user-1"),
        "max-jws": _payload(MAX, "user-1"),
    })

    user = User(id="user-1")
    iap.apply(user, {"x-apple-entitlement": "pro-jws"})
    assert user.plan == "u:ios_pro"

    user = User(id="user-1")
    iap.apply(user, {"x-apple-entitlement": "max-jws"})
    assert user.plan == "u:ios_max"


def test_set_form_still_grants_single_plan(monkeypatch):
    iap = _iap({PRO, MAX}, monkeypatch, {
        "pro-jws": _payload(PRO, "user-1"),
        "max-jws": _payload(MAX, "user-1"),
    })

    for jws in ("pro-jws", "max-jws"):
        user = User(id="user-1")
        iap.apply(user, {"x-apple-entitlement": jws})
        assert user.plan == "u:iap"


def test_verify_returns_payload_or_none(monkeypatch):
    iap = _iap({PRO: "u:ios_pro"}, monkeypatch, {
        "good": _payload(PRO, "user-1"),
        "wrong-product": _payload("com.other.sku", "user-1"),
        "expired": _payload(PRO, "user-1", expiresDate=(time.time() - 60) * 1000),
        "revoked": _payload(PRO, "user-1", revocationDate=1),
        "wrong-user": _payload(PRO, "someone-else"),
    })

    t = iap.verify("good", "user-1")
    assert t and t["productId"] == PRO
    for jws in ("wrong-product", "expired", "revoked", "wrong-user"):
        assert iap.verify(jws, "user-1") is None


def test_apply_never_overrides_org_plans(monkeypatch):
    iap = _iap({PRO: "u:ios_pro"}, monkeypatch, {"good": _payload(PRO, "user-1")})

    user = User(id="user-1", plan="org:enterprise")
    iap.apply(user, {"x-apple-entitlement": "good"})
    assert user.plan == "org:enterprise"
