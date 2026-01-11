import asyncio
import inspect
import traceback
import cloudpickle
import grpc
from concurrent import futures

try:
    from . import runtime_pb2
    from . import runtime_pb2_grpc
except ImportError:
    import runtime_pb2
    import runtime_pb2_grpc


class RuntimeServicer(runtime_pb2_grpc.RuntimeServicer):
    def Execute(self, request, context):
        try:
            func, args, kwargs = cloudpickle.loads(request.payload)
            result = func(*args, **kwargs)

            # Handle coroutines
            if inspect.iscoroutine(result):
                result = asyncio.run(result)

            # Handle async generators
            if inspect.isasyncgen(result):
                async def collect():
                    items = []
                    async for item in result:
                        items.append(item)
                    return items
                result = iter(asyncio.run(collect()))

            # Stream results for generators, single response otherwise
            if inspect.isgenerator(result):
                for chunk in result:
                    yield runtime_pb2.Response(data=cloudpickle.dumps(chunk))
            else:
                yield runtime_pb2.Response(data=cloudpickle.dumps(result))

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            yield runtime_pb2.Response(data=cloudpickle.dumps(error_msg), error=True)


def serve(port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    runtime_pb2_grpc.add_RuntimeServicer_to_server(RuntimeServicer(), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f"gRPC server listening on :{port}")
    server.wait_for_termination()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50051)
    args = parser.parse_args()
    serve(args.port)
