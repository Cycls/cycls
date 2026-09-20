# The smallest function: Python in a container, run wherever you point it.
#
#   uv run cycls run examples/functions/hello.py --n 8
#   uv run cycls run examples/functions/hello.py --n 8 --remote
#   uv run cycls deploy examples/functions/hello.py
import cycls


@cycls.function(image=cycls.Image().pip("numpy"))
def hello(n: int = 5):
    import numpy
    return (2 * numpy.arange(n)).tolist()


# After `cycls deploy`, call the frozen version from any machine with CYCLS_API_KEY:
#   import cycls
#   cycls.remote("hello")(8)
