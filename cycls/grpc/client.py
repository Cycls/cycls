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
                raise RuntimeError(f"Function execution failed: {result}")
            yield result

    def call(self, func, *args, **kwargs):
        """Execute and return single result (or list if multiple)."""
        results = list(self.execute(func, *args, **kwargs))
        return results[0] if len(results) == 1 else results

    def fire(self, func, *args, **kwargs):
        """Fire off execution without waiting for response."""
        stub = self._connect()
        payload = cloudpickle.dumps((func, args, kwargs))
        request = runtime_pb2.Request(payload=payload)
        # Start the stream - gRPC sends request immediately
        self._active_stream = stub.Execute(request)

    def wait_ready(self, timeout=10):
        """Wait for channel to be ready."""
        if self._channel is None:
            self._connect()
        try:
            grpc.channel_ready_future(self._channel).result(timeout=timeout)
            return True
        except grpc.FutureTimeoutError:
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
