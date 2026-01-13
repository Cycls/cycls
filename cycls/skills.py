"""Skills module for @cycls.agent() - Claude Code-style skills support."""

import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Skill:
    """A skill that can be invoked by the agent."""
    name: str
    description: str
    content: str
    path: Path
    allowed_tools: list[str] = field(default_factory=list)
    model: Optional[str] = None

    def to_tool_schema(self) -> dict:
        """Convert skill to a tool schema for the LLM."""
        return {
            "type": "function",
            "function": {
                "name": f"skill_{self.name.replace('-', '_')}",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The specific task to perform using this skill"
                        }
                    },
                    "required": ["task"]
                }
            }
        }


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith('---'):
        return {}, content

    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_str = parts[1].strip()
    body = parts[2].strip()

    # Simple YAML parsing (avoid external dependency)
    metadata = {}
    for line in frontmatter_str.split('\n'):
        line = line.strip()
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            # Handle lists (comma-separated)
            if ',' in value:
                value = [v.strip() for v in value.split(',')]
            # Handle booleans
            elif value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False
            metadata[key] = value

    return metadata, body


def load_skill(path: Path) -> Optional[Skill]:
    """Load a skill from a SKILL.md file or directory containing one."""
    if path.is_dir():
        skill_file = path / "SKILL.md"
        if not skill_file.exists():
            return None
        path = skill_file

    if not path.exists() or path.name != "SKILL.md":
        return None

    content = path.read_text(encoding='utf-8')
    metadata, body = _parse_frontmatter(content)

    name = metadata.get('name', path.parent.name)
    description = metadata.get('description', '')

    if not description:
        # Try to extract from first paragraph
        lines = body.split('\n\n')
        for line in lines:
            if line.strip() and not line.startswith('#'):
                description = line.strip()[:200]
                break

    allowed_tools = metadata.get('allowed-tools', [])
    if isinstance(allowed_tools, str):
        allowed_tools = [t.strip() for t in allowed_tools.split(',')]

    return Skill(
        name=name,
        description=description,
        content=body,
        path=path,
        allowed_tools=allowed_tools,
        model=metadata.get('model'),
    )


def load_skills(paths: list[str]) -> list[Skill]:
    """Load skills from a list of paths (files or directories)."""
    skills = []

    for path_str in paths:
        path = Path(path_str)

        if not path.exists():
            continue

        if path.is_file() and path.name == "SKILL.md":
            skill = load_skill(path)
            if skill:
                skills.append(skill)
        elif path.is_dir():
            # Check if this directory itself is a skill
            if (path / "SKILL.md").exists():
                skill = load_skill(path)
                if skill:
                    skills.append(skill)
            else:
                # Look for skill subdirectories
                for subdir in path.iterdir():
                    if subdir.is_dir():
                        skill = load_skill(subdir)
                        if skill:
                            skills.append(skill)

    return skills


def discover_skills(base_path: str = ".") -> list[Skill]:
    """Discover skills from .cycls/skills/ directory."""
    skills_dir = Path(base_path) / ".cycls" / "skills"
    if skills_dir.exists():
        return load_skills([str(skills_dir)])
    return []
