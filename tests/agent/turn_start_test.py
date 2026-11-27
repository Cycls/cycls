"""What a turn waits for before its first model call, logged once per run as `prelude`."""
from cycls._agent import prelude


def test_the_steps_before_the_first_call_are_taken_once():
    prelude.start()
    prelude.mark("chat history read")
    prelude.mark("skills")
    prelude.mark("skills")
    steps, total = prelude.take()
    assert set(steps) == {"chat history read", "skills"} and total >= 0
    assert prelude.take() is None                                 # logged once per run
    prelude.mark("design outline")                                # a later mark alone says nothing
    assert prelude.take() is None
