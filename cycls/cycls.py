from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Optional

from functools import wraps
import uvicorn, socket, httpx
import inspect

import logging
logging.basicConfig(level=logging.ERROR)

O = lambda x,y: print(f"✦/✧ {str(x).ljust(11)} | {y}")

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
key_path = os.path.join(current_dir, 'tuns')

class Message(BaseModel):
    handle: str
    content: str
    id: str
    history: Optional[List[Dict[str, str]]] = None

#!
def find_available_port(start_port):
    port = start_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
            port += 1

import asyncssh, asyncio
async def create_ssh_tunnel(x,y,z='tuns.sh'):
    try:
        async with asyncssh.connect(z,client_keys=[key_path],known_hosts=None) as conn:
            listener = await conn.forward_remote_port(x, 80, 'localhost', y)
            O("tunnel","open");print(" ")
            await listener.wait_closed()
            O("tunnel", "closed")
    except (OSError, asyncssh.Error) as e:
        O("tunnel",f"disconnected ({e})")

def register(handles, net, url, email):
    try:
        with httpx.Client() as client:
            response = client.post(f"{net}/register", json={"handles":handles, "url":url, "email":email})
            if response.status_code==200:
                data = (response.json()).get("content")
                for i in data:
                    O(i[0],f"{net}/{i[1]}")
            else:
                print("✦/✧ failed to register ⚠️")
    except Exception as e:
        print(f"An error occurred: {e}")

class Cycls:
    def __init__(self, url="", net="https://cycls.com", port=find_available_port(8001), email=None):
        import uuid
        self.subdomain = str(uuid.uuid4())[:8]
        self.server = FastAPI()
        self.net = net
        self.port = port
        self.url = url
        self.apps = {}
        self.prod = False
        self.email = email

    def __call__(self, handle):
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return StreamingResponse(await func(*args, **kwargs))
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                return StreamingResponse(func(*args, **kwargs))
            wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

            if self.url != "": self.prod=True #!
            if not self.prod:
                self.apps[handle + "-dev"] = wrapper
            else:
                self.apps[handle] = wrapper

            return wrapper
        return decorator
    
    async def gateway(self, request: Request):
        data = await request.json()
        handle = data.get('handle')
        if handle in self.apps:
            func = self.apps[handle]
            message = Message(**data)
            return await func(message) if inspect.iscoroutinefunction(func) else func(message)
        return {"error": "Handle not found"}

    def push(self):
        if self.email:
            O("email",self.email)
        O("port",self.port)
        if self.prod:
            O("mode",f"production @ {self.url}")
            register(list(self.apps.keys()), self.net, self.url+"/gateway", self.email)
        else:
            self.url = f"http://{self.subdomain}-cycls.tuns.sh"
            O("mode","development")
            O("docs","for more information, visit https://github.com/Cycls/cycls-py")
            register(list(self.apps.keys()), self.net, self.url+"/gateway", self.email)

        self.server.post("/gateway")(self.gateway)
        @self.server.on_event("startup")
        def startup_event():
            if self.prod:
                pass
            else:
                asyncio.create_task(create_ssh_tunnel(f"{self.subdomain}-cycls", self.port))
        try:
            uvicorn.run(self.server, host="127.0.0.1", port=self.port, log_level="error")
        except KeyboardInterrupt:
            print(" ");O("exit","done")

    async def call(self, handle, content):
        data = {"handle":handle, "content":content, "session":{}, "agent":"yes"}
        try:
            url = f"{self.net}/stream/"
            async with httpx.AsyncClient(timeout=20) as client, client.stream("POST", url, json=data) as response:
                if response.status_code != 200:
                    print("http error")
                async for token in response.aiter_text():
                    yield token
        except Exception as e:
            print("Exception", e)
        
# poetry publish --build