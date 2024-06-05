from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, PlainTextResponse

from functools import wraps
import uvicorn, socket, httpx

from concurrent.futures import ThreadPoolExecutor
import time, subprocess

class DictAsObject:
    def __init__(self, dict_data):
        self.__dict__.update(dict_data)

    def __getattr__(self, item):
        return self.__dict__.get(item)

def find_available_port(start_port):
    port = start_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
            port += 1

class Cycls:
    def __init__(self, network="https://cycls.com", port=find_available_port(8001),url="",debug=True):
        self.server = FastAPI()
        self.network = network
        self.port = port
        self.handle = None
        self.url = url
        self.debug = debug

    def __call__(self, handle): 
        self.handle = handle
        def decorator(func):
            @wraps(func)
            async def decorated_func(x):
                request_json = await x.json()
                return await func(DictAsObject(request_json))
            self.server.post('/main')(decorated_func)
            self.publish()
            return decorated_func
        return decorator


    def publish(self):
        prod=False
        if self.url != "":
            prod=True

        if self.debug: print("✦/✧ debug = True")
        if prod:
            print("✦/✧","production mode",f"(url: {self.url}, port: {self.port})")
        else:
            print("✦/✧","development mode",f"(port: {self.port})")
            # self.url = f"https://{self.handle}-cycls.tuns.sh"
            self.url = f"https://{self.handle}-cycls.serveo.net"

        print("")
        print("✦/✧",f"https://cycls.com/@{self.handle}")
        print("")

        with ThreadPoolExecutor() as executor:
            if not prod:
                self.register('dev')
                executor.submit(self.tunnel)
            else:
                self.register('prod')

            if self.debug:
                executor.submit(uvicorn.run(self.server, host="127.0.0.1", port=self.port)) # perhaps keep traces?
            else:
                executor.submit(uvicorn.run(self.server, host="127.0.0.1", port=self.port, log_level="critical")) # perhaps keep traces?

    def register(self, mode):
        try:
            with httpx.Client() as client:
                response = client.post(f"{self.network}/register", json={"handle": f"@{self.handle}", "url": self.url, "mode": mode})
                if response.status_code==200:
                    print(f"✦/✧ published 🎉")
                    print("")
                else:
                    print("✦/✧ failed to register ⚠️") # exit app
        except Exception as e:
            print(f"An error occurred: {e}")

    def tunnel(self):
        # ssh_command = ['ssh', '-q', '-i', 'tuns', '-o', 'StrictHostKeyChecking=no', '-R', f'{self.handle}-cycls:80:localhost:{self.port}', 'tuns.sh']
        ssh_command = ['ssh', '-q', '-i', 'key.pub', '-o', 'StrictHostKeyChecking=no', '-R', f'{self.handle}-cycls:80:localhost:{self.port}', 'serveo.net']
        try:
            if self.debug: 
                process = subprocess.run(ssh_command,stdin=subprocess.DEVNULL) # very tricky! STDIN is what was messing with me
            else:
                process = subprocess.run(ssh_command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"An error occurred: {e}") # exit app

from types import AsyncGeneratorType
Text = lambda x: StreamingResponse(x, media_type='text/event-stream') if type(x)==AsyncGeneratorType else PlainTextResponse(str(x))
Message = Request

# poetry publish --build

# push = Cycls(debug=True,port=8000)

# @push("hub")
# async def entry_point(x:Message):
#     return Text(x.content)