import cycls

@cycls.function(image=cycls.Image().pip("numpy"))
def ziad(x, y):
    import numpy
    return (y*numpy.arange(x)).tolist()

print(ziad.run(5,2))