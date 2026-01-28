"""
Settings Manager: Handles loading and retrieving configuration from TOML and Environment.
"""

import os
from pathlib import Path

# Try multiple TOML parsers in order of preference
try:
    import tomllib  # Python 3.11+
    def load_toml(f):
        return tomllib.load(f)
    TOML_MODE = "binary"
except ImportError:
    try:
        import toml
        def load_toml(f):
            return toml.load(f)
        TOML_MODE = "text"
    except ImportError:
        try:
            import tomli
            def load_toml(f):
                return tomli.load(f)
            TOML_MODE = "binary"
        except ImportError:
            # Fallback: simple TOML parser for basic cases
            import re
            def load_toml(f):
                content = f.read() if hasattr(f, 'read') else open(f).read()
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                return _simple_toml_parse(content)
            TOML_MODE = "text"

            def _simple_toml_parse(content: str) -> dict:
                """Simple TOML parser for basic config files."""
                result = {}
                current_section = result
                section_path = []

                for line in content.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # Section header
                    if line.startswith('['):
                        section_name = line.strip('[]').strip()
                        parts = section_name.split('.')
                        current_section = result
                        for part in parts:
                            if part not in current_section:
                                current_section[part] = {}
                            current_section = current_section[part]
                        section_path = parts
                        continue

                    # Key-value pair
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # Parse value
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        elif value.lower() == 'true':
                            value = True
                        elif value.lower() == 'false':
                            value = False
                        elif value.isdigit():
                            value = int(value)
                        elif re.match(r'^[\d.]+$', value):
                            try:
                                value = float(value)
                            except:
                                pass
                        elif value.startswith('[') and value.endswith(']'):
                            # Simple array parsing
                            arr_content = value[1:-1].strip()
                            if arr_content:
                                items = []
                                for item in arr_content.split(','):
                                    item = item.strip().strip('"\'')
                                    items.append(item)
                                value = items
                            else:
                                value = []
                        elif value.startswith('{') and value.endswith('}'):
                            # Inline table - basic parsing
                            value = _parse_inline_table(value)

                        current_section[key] = value

                return result

            def _parse_inline_table(s: str) -> dict:
                """Parse inline TOML table like { key = value, key2 = value2 }"""
                result = {}
                s = s.strip()[1:-1]  # Remove { }
                for part in s.split(','):
                    if '=' in part:
                        k, v = part.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"\'')
                        if v.lower() == 'true':
                            v = True
                        elif v.lower() == 'false':
                            v = False
                        elif v.isdigit():
                            v = int(v)
                        elif re.match(r'^[\d.]+$', v):
                            try:
                                v = float(v)
                            except:
                                pass
                        result[k] = v
                return result
from typing import Any, Dict, Optional
from dotenv import load_dotenv

class SettingsManager:
    """Centralizes access to TOML and environment variables."""

    def __init__(self, config_path: str = "config.toml"):
        self.base_dir = Path(__file__).parent
        
        # Load .env from multiple possible locations
        env_paths = [
            self.base_dir.parent / "private_context" / ".env",
            self.base_dir.parent / ".env",
            self.base_dir / ".env",
            Path.cwd() / "private_context" / ".env",
            Path.cwd() / ".env",
        ]
        
        for env_path in env_paths:
            if env_path.exists():
                load_dotenv(env_path, override=False)
                break
        
        # Try finding config.toml in deep_research/ or root/
        possible_paths = [
            self.base_dir / config_path,
            self.base_dir.parent / config_path,
            Path.cwd() / config_path,
            Path.cwd() / "deep_research" / config_path
        ]
        
        self.config_path = None
        for p in possible_paths:
            if p.exists():
                self.config_path = str(p)
                break
        
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Loads TOML configuration."""
        if self.config_path and os.path.exists(self.config_path):
            try:
                mode = "rb" if TOML_MODE == "binary" else "r"
                with open(self.config_path, mode, encoding=None if TOML_MODE == "binary" else "utf-8") as f:
                    return load_toml(f)
            except Exception as e:
                print(f"⚠️ Error loading {self.config_path}: {e}")
        else:
            print(f"⚠️ config.toml not found in any expected location.")
        return {}

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level config value."""
        return self._config.get(key, default)

    def get_nested(self, section: str, *keys: str, default: Any = None) -> Any:
        """Get a value from a nested TOML section. Supporting multiple levels."""
        val = self._config.get(section, {})
        if not keys:
            return val if val else default
            
        for k in keys[:-1]:
            if isinstance(val, dict):
                val = val.get(k, {})
            else:
                return default
        
        if isinstance(val, dict):
            return val.get(keys[-1], default)
        return default

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get an environment variable."""
        return os.environ.get(key, default)

    def is_true(self, key: str, section: Optional[str] = None) -> bool:
        """Checks if a boolean setting is True."""
        if section:
            val = self.get_nested(section, key)
        else:
            val = self.get(key)
        return str(val).lower() in ("true", "1", "yes", "on")

# Singleton instance
settings = SettingsManager()
