import pytest

import cycls


def test_schedule_rejects_server_contract_functions():
    with pytest.raises(ValueError, match="remote endpoints"):
        @cycls.function(schedule=cycls.Cron("0 3 * * *"))
        def server(port):
            pass


def test_function_spec_carries_schedule_only_when_set():
    @cycls.function(schedule=cycls.Cron("0 3 * * *", timezone="Asia/Riyadh"))
    def scheduled():
        pass

    @cycls.function(schedule=cycls.Cron("0 3 * * *"))
    def utc_scheduled():
        pass

    @cycls.function()
    def unscheduled():
        pass

    assert scheduled.spec["schedule"] == "0 3 * * *"
    assert scheduled.spec["timezone"] == "Asia/Riyadh"
    assert utc_scheduled.spec["schedule"] == "0 3 * * *"
    assert "timezone" not in utc_scheduled.spec
    assert "schedule" not in unscheduled.spec


def test_executor_reentry_drops_schedule_but_keeps_volumes():
    @cycls.function(schedule=cycls.Cron("0 3 * * *", timezone="Asia/Riyadh"),
                    volumes={"/data": cycls.Volume("shared")})
    def add(x, y):
        return x + y

    from cycls._function import Function
    executor_spec = {k: v for k, v in add.spec.items() if k not in ("schedule", "timezone")}
    executor = Function(lambda: None, "exec-abc123", **executor_spec)
    assert "schedule" not in executor.spec
    assert "timezone" not in executor.spec
    assert executor.spec["volumes"] == add.spec["volumes"]
