# uv run python examples/function/c.py
import cycls

C_CODE = r"""
#include <stdio.h>
int main() {
    for (int i = 10; i >= 1; --i) {
        for (int j = 1; j <= i; ++j) printf("*");
        printf("\n");
    }
    return 0;
}
"""

@cycls.function(image=cycls.Image().apt("gcc", "libc6-dev"))
def triangle():
    import subprocess
    with open("triangle.c", "w") as f:
        f.write(C_CODE)
    subprocess.run(["gcc", "triangle.c", "-o", "triangle"], check=True)
    return subprocess.run(["./triangle"], check=True, capture_output=True, text=True).stdout

print(triangle.run())
