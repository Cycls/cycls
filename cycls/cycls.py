from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Optional

from functools import wraps
import uvicorn, socket, httpx
import inspect

import logging
logging.basicConfig(level=logging.ERROR)

class Message(BaseModel):
    handle: str
    content: str
    session_id: str
    history: Optional[List[Dict[str, str]]] = None

def find_available_port(start_port):
    port = start_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
            port += 1

import asyncssh, asyncio
async def create_ssh_tunnel(x,y,z='tuns.karpov.solutions'):
    try:
        async with asyncssh.connect(z,port=2222,known_hosts=None) as conn:
            await conn.forward_remote_port(x, 80, 'localhost', y)
            print("✦/✧","tunnel established\n")
            await asyncio.Future()  # run forever
    except (OSError, asyncssh.Error) as e:
        print("✦/✧",f"tunnel disconnected: {e}")

def register(handle, network, url, mode):
    try:
        with httpx.Client() as client:
            response = client.post(f"{network}/register", json={"handle":f"@{handle}", "url":url, "mode":mode})
            if response.status_code==200:
                print(f"✦/✧ published 🎉")
                print("")
            else:
                print("✦/✧ failed to register ⚠️")
    except Exception as e:
        print(f"An error occurred: {e}")

async def run_server(x,y):
    config = uvicorn.Config(x, host="127.0.0.1", port=y, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()

class Cycls:
    def __init__(self,network="https://cycls.com", port=find_available_port(8001),url=""):
        self.handle = None
        self.server = FastAPI()
        self.network = network
        self.port = port
        self.url = url

    def __call__(self, handle):
        self.handle = handle
        def decorator(func):
            if inspect.iscoroutinefunction(func):
                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    return await func(*args, **kwargs)
                self.server.post('/main')(async_wrapper)
                asyncio.run(self.publish())
                return async_wrapper
            else:
                @wraps(func)
                def sync_wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                self.server.post('/main')(sync_wrapper)
                asyncio.run(self.publish())
                return sync_wrapper
        return decorator

    async def publish(self):
        prod=False
        if self.url != "":
            prod=True

        print(f"\n✦/✧ serving at port: {self.port}\n")
        if prod:
            print("✦/✧","production mode",f"url: {self.url}\n")
        else:
            self.url = f"http://{self.handle}-cycls.tuns.karpov.solutions"
            print("✦/✧","development mode\n")
            t2 = asyncio.create_task(run_server(self.server,self.port))
            
        print("✦/✧",f"visit app: {self.network}/@{self.handle}","\n")

        t1 = asyncio.create_task(create_ssh_tunnel(f"{self.handle}-cycls", self.port))
        await asyncio.gather(t1, t2) if not prod else asyncio.gather(t2)

Text = StreamingResponse