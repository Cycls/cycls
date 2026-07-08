# uv run cycls deploy examples/function/remote.py --remote
import cycls

@cycls.function(image=cycls.Image().pip("numpy"))
def simulate(n=1_000_000):
    import numpy as np
    pts = np.random.rand(int(n), 2)
    return float(4 * ((pts ** 2).sum(axis=1) <= 1).mean())

# remote call from any machine+CYCLS_KEYS
# import cycls; print(cycls.remote("simulate")(10_000_000))
# import cycls; print(cycls.remote("simulate").map([10**6] * 100))