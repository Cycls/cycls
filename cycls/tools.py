"""Built-in tools for @cycls.agent() agents."""

import os
import subprocess
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class Tool:
    """A tool that can be called by the agent."""
    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]

    def to_schema(self) -> dict:
        """Convert to OpenAI-compatible tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def execute(self, **kwargs) -> str:
        """Execute the tool with given arguments."""
        return self.func(**kwargs)


def _read(file_path: str, offset: int = None, limit: int = None) -> str:
    """Read a file from the filesystem."""
    try:
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"
        if path.is_dir():
            return f"Error: {file_path} is a directory, not a file"

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        if offset is not None:
            lines = lines[offset:]
        if limit is not None:
            lines = lines[:limit]

        start = (offset or 0) + 1
        numbered = [f"{i:6}\t{line.rstrip()}" for i, line in enumerate(lines, start=start)]
        return '\n'.join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


def _write(file_path: str, content: str) -> str:
    """Write content to a file."""
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Edit a file by replacing old_string with new_string."""
    try:
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        if old_string not in content:
            return f"Error: old_string not found in {file_path}"

        count = content.count(old_string)
        if count > 1 and not replace_all:
            return f"Error: old_string appears {count} times. Use replace_all=true or provide more context."

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        replacements = count if replace_all else 1
        return f"Successfully edited {file_path} ({replacements} replacement{'s' if replacements > 1 else ''})"
    except Exception as e:
        return f"Error editing file: {e}"


def _bash(command: str, timeout: int = 120) -> str:
    """Execute a bash command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {e}"


def _glob(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern."""
    try:
        base = Path(path)
        matches = sorted(base.glob(pattern))
        if not matches:
            return f"No files matching pattern: {pattern}"
        return '\n'.join(str(m) for m in matches[:100])
    except Exception as e:
        return f"Error: {e}"


def _grep(pattern: str, path: str = ".", include: str = None) -> str:
    """Search for a regex pattern in files."""
    try:
        results = []
        base = Path(path)

        if base.is_file():
            files = [base]
        else:
            if include:
                files = list(base.rglob(include))
            else:
                files = [f for f in base.rglob('*') if f.is_file()]

        regex = re.compile(pattern)
        for file in files[:1000]:
            if file.is_file():
                try:
                    with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append(f"{file}:{i}: {line.rstrip()}")
                                if len(results) >= 100:
                                    break
                except:
                    pass
            if len(results) >= 100:
                break

        if not results:
            return f"No matches for pattern: {pattern}"
        return '\n'.join(results)
    except Exception as e:
        return f"Error: {e}"


read = Tool(
    name="read",
    description="Read a file from the filesystem. Returns file contents with line numbers.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or relative path to the file"},
            "offset": {"type": "integer", "description": "Line number to start from (0-indexed)"},
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
        },
        "required": ["file_path"],
    },
    func=_read,
)

write = Tool(
    name="write",
    description="Write content to a file. Creates parent directories if needed.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file to write"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        "required": ["file_path", "content"],
    },
    func=_write,
)

edit = Tool(
    name="edit",
    description="Edit a file by replacing old_string with new_string. The old_string must be unique unless replace_all is true.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "old_string": {"type": "string", "description": "The exact string to replace"},
            "new_string": {"type": "string", "description": "The replacement string"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences", "default": False},
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    func=_edit,
)

bash = Tool(
    name="bash",
    description="Execute a bash command and return its output.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
        },
        "required": ["command"],
    },
    func=_bash,
)

glob = Tool(
    name="glob",
    description="Find files matching a glob pattern (e.g., '**/*.py').",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match"},
            "path": {"type": "string", "description": "Base directory to search from", "default": "."},
        },
        "required": ["pattern"],
    },
    func=_glob,
)

grep = Tool(
    name="grep",
    description="Search for a regex pattern in files. Returns matching lines with file paths and line numbers.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "File or directory to search", "default": "."},
            "include": {"type": "string", "description": "Glob pattern to filter files (e.g., '*.py')"},
        },
        "required": ["pattern"],
    },
    func=_grep,
)

DEFAULT_TOOLS = [read, write, edit, bash, glob, grep]

def get_tool(name: str) -> Tool:
    """Get a tool by name."""
    tools = {t.name: t for t in DEFAULT_TOOLS}
    return tools.get(name)
