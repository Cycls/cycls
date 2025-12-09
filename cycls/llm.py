import re
import io
import os
import asyncio
import httpx
import warnings
import openai
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
import pandas as pd

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')



class FileHandlerMixin:
    """
    Handles file downloading, parsing (PDF/Docs/etc), and message preprocessing.
    """
    async def _download_file(self, url):
        """Downloads file into memory bytes."""
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
            return io.BytesIO(response.content)

    def _parse_document_sync(self, file_stream, filename):
        """CPU-bound parsing logic (PDF, Docx, Excel)."""
        ext = os.path.splitext(filename)[1].lower()
        try:
            if ext == '.pdf':
                reader = PdfReader(file_stream)
                text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
            elif ext in ['.docx', '.doc']:
                doc = Document(file_stream)
                text = "\n".join([p.text for p in doc.paragraphs])
            elif ext in ['.xlsx', '.xls', '.csv']:
                df = pd.read_csv(file_stream, nrows=500) if ext == '.csv' else pd.read_excel(file_stream, nrows=500)
                text = df.to_markdown(index=False)
            else:
                text = file_stream.getvalue().decode('utf-8', errors='ignore')

            return f"\n[System: Attached file '{filename}']\n{text}\n[End of file]\n"
        except Exception as e:
            return f"\n[System: Error reading file '{filename}': {str(e)}]\n"

    async def _process_file_task(self, url, filename):
        """Async task to download and parse a document."""
        try:
            stream = await self._download_file(url)
            return await asyncio.to_thread(self._parse_document_sync, stream, filename)
        except Exception as e:
            return f"[Error downloading {filename}]"

    async def _preprocess_messages(self, messages):
        """
        Standardizes messages:
        - Documents -> Text
        - Images -> Kept as 'image_url' (OpenAI format)
        """
        processed = []
        for msg in messages:
            new_msg = msg.copy()
            if isinstance(new_msg.get('content'), list):
                new_content = []
                tasks = []
                for item in new_msg['content']:
                    if item.get('type') == 'file':
                        # Extract URL
                        txt = item.get('text', '')
                        url_match = re.search(r'File URL:\s*(https?://[^\s]+)', txt)
                        name_match = re.search(r'\[File attached:\s*(.*?)\]', txt)
                        
                        if url_match:
                            url = url_match.group(1)
                            fname = name_match.group(1) if name_match else "file"
                            ext = os.path.splitext(fname)[1].lower()

                            # If Image -> Keep as URL (OpenAI standard)
                            if ext in ['.jpg', '.png', '.jpeg', '.webp']:
                                new_content.append({"type": "image_url", "image_url": {"url": url}})
                            # If Doc -> Queue for parsing
                            else:
                                tasks.append(self._process_file_task(url, fname))
                    else:
                        new_content.append(item)
                
                if tasks:
                    results = await asyncio.gather(*tasks)
                    for r in results: new_content.append({"type": "text", "text": r})
                
                new_msg['content'] = new_content
            processed.append(new_msg)
        return processed



class OpenAI(FileHandlerMixin):
    def __init__(self, api_key=None, model="gpt-4o", temperature=1.0, **kwargs):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.kwargs = kwargs
        self._client = None

    def _get_client(self):
        if not self._client:
            self._client = openai.AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def stream(self, messages, **override):
        # 1. Mixin handles PDF/Doc parsing
        clean_msgs = await self._preprocess_messages(messages)
        
        # 2. Standard OpenAI Call
        client = self._get_client()
        params = {
            "model": self.model, "messages": clean_msgs, "stream": True,
            "temperature": self.temperature, **self.kwargs, **override
        }
        response = await client.chat.completions.create(**params)
        
        async def generator():
            async for chunk in response:
                if chunk.choices[0].delta.content: yield chunk.choices[0].delta.content
        return generator()



class Gemini(FileHandlerMixin):
    def __init__(self, api_key=None, model="gemini-2.5-pro", temperature=1.0, **kwargs):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.kwargs = kwargs
        genai.configure(api_key=self.api_key)

    async def _convert_to_gemini_format(self, openai_messages):
        """
        Converts OpenAI-style messages to Gemini format.
        Also downloads images because Gemini prefers inline data.
        """
        gemini_history = []
        system_instruction = None

        for msg in openai_messages:
            role = msg['role']
            content_parts = []
            
            # Handle System Prompt (Gemini separates this)
            if role == "system":
                system_instruction = msg['content']
                continue
            
            # Map Roles (OpenAI 'assistant' -> Gemini 'model')
            gemini_role = "model" if role == "assistant" else "user"

            # Process Content
            raw_content = msg['content']
            if isinstance(raw_content, str):
                content_parts.append(raw_content)
            elif isinstance(raw_content, list):
                for part in raw_content:
                    if part['type'] == 'text':
                        content_parts.append(part['text'])
                    
                    elif part['type'] == 'image_url':
                        # DOWNLOAD IMAGE (Reusing Mixin's downloader!)
                        url = part['image_url']['url']
                        try:
                            stream = await self._download_file(url)
                            mime_type = "image/png" 
                            if url.endswith(".jpg") or url.endswith(".jpeg"): mime_type = "image/jpeg"
                            elif url.endswith(".webp"): mime_type = "image/webp"
                            
                            # Gemini wants raw data dict
                            content_parts.append({
                                "mime_type": mime_type,
                                "data": stream.getvalue()
                            })
                        except:
                            content_parts.append(f"[Error downloading image: {url}]")

            gemini_history.append({"role": gemini_role, "parts": content_parts})
        
        return gemini_history, system_instruction

    async def stream(self, messages, **override):
        # 1. Mixin handles PDF/Doc parsing
        clean_msgs = await self._preprocess_messages(messages)

        # 2. Convert to Gemini Format
        history, system_inst = await self._convert_to_gemini_format(clean_msgs)

        # 3. Initialize Model
        model = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_inst,
        )

        # 4. Generate Stream
        if not history: return # No content

        last_msg = history.pop() # Remove last message to use as prompt
        chat = model.start_chat(history=history)
        
        response = await chat.send_message_async(
            last_msg['parts'], 
            stream=True,
            generation_config=genai.types.GenerationConfig(
                temperature=self.temperature
            )
        )

        async def generator():
            async for chunk in response:
                if chunk.text: yield chunk.text
        return generator()