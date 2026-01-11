import cycls

@cycls.function(pip=["numpy", "pandas", "tabulate"])
def monte_carlo(num_points: int = 1000000):
    import numpy as np; import pandas as pd
    points = np.random.rand(num_points, 2)
    distances = np.sqrt(points[:, 0]**2 + points[:, 1]**2)
    is_inside_circle = distances <= 1
    points_in_circle = np.sum(is_inside_circle)
    pi_estimate = 4 * (points_in_circle / num_points)
    df = pd.DataFrame({'X-coordinate': points[:10, 0], 'Y-coordinate': points[:10, 1],
                       'Distance from Origin': distances[:10], 'Is Inside Circle': is_inside_circle[:10]})
    markdown_table = df.to_markdown(index=False)

    print("--- Monte Carlo Simulation: Sample Data ---")
    print(markdown_table)
    print("'\n-----------------------------------------\n")
    print(f"Total points generated: {num_points}")
    print(f"Points inside unit circle: {points_in_circle}")
    print(f"Final estimated value of Pi: {pi_estimate}")
    
    return pi_estimate.tolist()

print(f"The final returned value is: {monte_carlo.run(num_points=100000)}")