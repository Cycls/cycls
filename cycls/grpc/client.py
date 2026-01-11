import cloudpickle
import grpc

try:
    from . import runtime_pb2
    from . import runtime_pb2_grpc
except ImportError:
    import runtime_pb2
    import runtime_pb2_grpc


class RuntimeClient:
    def __init__(self, host='localhost', port=50051, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._channel = None
        self._stub = None

    def _connect(self):
        if self._channel is None:
            self._channel = grpc.insecure_channel(f'{self.host}:{self.port}')
            self._stub = runtime_pb2_grpc.RuntimeStub(self._channel)
        return self._stub

    def execute(self, func, *args, **kwargs):
        """Execute function and yield streamed results."""
        stub = self._connect()
        payload = cloudpickle.dumps((func, args, kwargs))
        request = runtime_pb2.Request(payload=payload)

        for response in stub.Execute(request, timeout=self.timeout):
            result = cloudpickle.loads(response.data)
            if response.error:
                raise RuntimeError(result)
            yield result

    def call(self, func, *args, **kwargs):
        """Execute and return single result (or list if multiple)."""
        results = list(self.execute(func, *args, **kwargs))
        return results[0] if len(results) == 1 else results

    def ping(self, timeout=2):
        """Check if server is ready."""
        try:
            stub = self._connect()
            payload = cloudpickle.dumps((lambda: "pong", [], {}))
            request = runtime_pb2.Request(payload=payload)
            for response in stub.Execute(request, timeout=timeout):
                return True
            return False
        except grpc.RpcError:
            return False

    def close(self):
        if self._channel:
            self._channel.close()
            self._channel = None
            self._stub = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
