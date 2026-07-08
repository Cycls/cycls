# uv run cycls deploy examples/function/remote.py --remote
#
# Then, from ANY machine with cycls + CYCLS_API_KEY — no Docker needed:
#   import cycls
#   print(cycls.remote("simulate")(10_000_000))
import cycls

@cycls.function(image=cycls.Image().pip("numpy"))
def simulate(n=1_000_000):
    import numpy as np
    pts = np.random.rand(int(n), 2)
    return float(4 * ((pts ** 2).sum(axis=1) <= 1).mean())

if __name__ == "__main__":
    print(simulate.remote(1_000_000))
