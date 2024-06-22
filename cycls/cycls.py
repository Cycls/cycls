from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel

from functools import wraps
import uvicorn, socket, httpx
import inspect

from concurrent.futures import ThreadPoolExecutor
import time, subprocess

import logging
logging.basicConfig(level=logging.ERROR)

from typing import List, Dict, Optional
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
                self.publish()
                return async_wrapper
            else:
                @wraps(func)
                def sync_wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                self.server.post('/main')(sync_wrapper)
                self.publish()
                return sync_wrapper
        return decorator

    def publish(self):
        prod=False
        if self.url != "":
            prod=True

        print(f"\n✦/✧ serving at port: {self.port}\n")
        if prod:
            print("✦/✧","production mode",f"url: {self.url}\n")
        else:
            self.url = f"http://{self.handle}-cycls.tuns.karpov.solutions"
            print("✦/✧","development mode\n")
            
        print("✦/✧",f"visit app: {self.network}/@{self.handle}","\n")

        with ThreadPoolExecutor() as executor:
            if not prod:
                self.register('dev')
                executor.submit(self.tunnel)
            else:
                self.register('prod')

            executor.submit(uvicorn.run(self.server, host="127.0.0.1", port=self.port, log_level="error")) # perhaps keep traces?

    def register(self, mode):
        try:
            with httpx.Client() as client:
                response = client.post(f"{self.network}/register", json={"handle": f"@{self.handle}", "url": self.url, "mode": mode})
                if response.status_code==200:
                    print(f"✦/✧ published 🎉")
                    print("")
                else:
                    print("✦/✧ failed to register ⚠️")
        except Exception as e:
            print(f"An error occurred: {e}")

    def tunnel(self):
        ssh_command = ['ssh', '-o', 'StrictHostKeyChecking=no', '-p', '2222', '-R', f'{self.handle}-cycls:80:localhost:{self.port}', 'tuns.karpov.solutions']
        try:
            process = subprocess.run(ssh_command,stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as e:
            print(f"ssh error: {e}")

Text = StreamingResponse