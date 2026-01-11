import cycls

@cycls.function(pip=["numpy"])
def ticker(x):
    import numpy as np
    import time

    for i in range(10):
        print(f"Tick {i+1}: {x}")
        time.sleep(1)

    print(f"The square of {x} is {np.square(x)}")
    return np.square(x).tolist()

print(ticker.run(2) + 10)
