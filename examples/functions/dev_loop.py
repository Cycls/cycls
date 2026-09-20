# The cloud dev loop, with no Docker. Edit anything, save, and the result
# reprints in about a second:
#
#   uv run cycls run examples/functions/dev_loop.py --remote
#   uv run cycls run examples/functions/dev_loop.py --remote --n 1000
import cycls

@cycls.function(image=cycls.Image().pip("numpy", "pandas"))
def simulate(n=1_000_000):
    import numpy as np
    pts = np.random.rand(int(n), 2)
    return float(4 * ((pts ** 2).sum(axis=1) <= 1).mean())

@cycls.local_entrypoint
def main(n: int = 1_000_000):
    print(simulate.remote(n))
    print(simulate.map([10, 20, 30]))

# Or deploy it and call the frozen version by name, from any machine that has
# CYCLS_API_KEY:
#   uv run cycls deploy examples/functions/dev_loop.py
#   python -c 'import cycls; print(cycls.remote("simulate")(10_000_000))'
