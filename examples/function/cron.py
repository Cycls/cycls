import cycls

reports = cycls.Volume("daily-reports")


@cycls.function(schedule=cycls.Cron("*/5 * * * *", timezone="Asia/Riyadh"),
                volumes={"/reports": reports})
def heartbeat():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with open(f"/reports/{now:%Y-%m-%d}.log", "a") as f:
        f.write(f"{now.isoformat()} alive\n")


if __name__ == "__main__":
    heartbeat.deploy()
