"""cycls.Cron — fire a deployed function on a schedule.

The platform calls the deployment's frozen invocation with no arguments,
at-least-once. Write idempotent outputs (date-keyed files in a volume) and
retries become harmless.
"""


class Cron:
    def __init__(self, cron, timezone=None):
        self.cron = cron
        self.timezone = timezone
