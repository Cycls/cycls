import cycls

@cycls.app()
async def error_test(context):
    """Test app for error propagation to UI."""
    msg = context.last_message.lower()

    if "immediate" in msg:
        # Error before any yield
        raise RuntimeError("Immediate failure - no yields happened!")

    yield "Processing your request...\n\n"

    if "error" in msg or "fail" in msg:
        # Error mid-stream
        raise ValueError(f"Intentional error triggered by: {context.last_message}")

    if "divide" in msg:
        # Classic error
        x = 1 / 0

    yield "Everything worked fine! ✓\n\n"
    yield "Try typing 'error', 'fail', 'divide', or 'immediate' to trigger errors."

error_test.local()
