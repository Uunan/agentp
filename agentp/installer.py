"""AgentP - Automated Code Agent Integration Module.

Supported Code Agents:
1. OpenCode     (Linux, macOS, Windows)
2. Claude Code  (Linux, macOS, Windows)
3. Cursor       (Linux, macOS, Windows)
4. Antigravity  (Linux, macOS, Windows)
"""
import json
import os
import sys
from pathlib import Path

DEFAULT_PORT = 8000
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_PORT}/v1"
DEFAULT_ANTHROPIC_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
DEFAULT_DUMMY_KEY = "local-agentp-key"


def get_platform():
    """Returns operating system name: 'windows', 'macos', 'linux'."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _safe_load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _safe_save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def configure_opencode(port: int = DEFAULT_PORT, model_id: str = "nvidia/nemotron-3.5-lightning-30b-a3b") -> dict:
    """Adds the AgentP provider to opencode.json for OpenCode."""
    home = Path.home()
    base_url = f"http://127.0.0.1:{port}/v1"
    
    # Standard opencode path: ~/.config/opencode/opencode.json (across all platforms including Windows)
    target_path = home / ".config" / "opencode" / "opencode.json"
    
    data = _safe_load_json(target_path)
    if "$schema" not in data:
        data["$schema"] = "https://opencode.ai/config.json"
    
    # OpenCode schema: "provider" is an object mapping provider_id -> ProviderConfig
    if not isinstance(data.get("provider"), dict):
        data["provider"] = {}
    if "providers" in data:
        del data["providers"]
        
    providers = data["provider"]
    providers["agentp"] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "AgentP Privacy Proxy",
        "options": {
            "baseURL": base_url,
            "apiKey": DEFAULT_DUMMY_KEY
        },
        "models": {
            model_id: {
                "name": f"AgentP ({model_id.split('/')[-1]})"
            }
        }
    }
    data["model"] = f"agentp/{model_id}"
    
    _safe_save_json(target_path, data)
    return {
        "agent": "OpenCode",
        "status": "success",
        "file": str(target_path),
        "endpoint": base_url,
        "model": f"agentp/{model_id}"
    }


def configure_claude_code(port: int = DEFAULT_PORT) -> dict:
    """Adds ANTHROPIC_BASE_URL to ~/.claude/settings.json for Claude Code."""
    home = Path.home()
    target_path = home / ".claude" / "settings.json"
    anthropic_url = f"http://127.0.0.1:{port}"
    
    data = _safe_load_json(target_path)
    env = data.setdefault("env", {})
    env["ANTHROPIC_BASE_URL"] = anthropic_url
    env["ANTHROPIC_AUTH_TOKEN"] = DEFAULT_DUMMY_KEY
    
    _safe_save_json(target_path, data)
    return {
        "agent": "Claude Code",
        "status": "success",
        "file": str(target_path),
        "endpoint": anthropic_url,
        "env_var": "ANTHROPIC_BASE_URL"
    }


def configure_cursor(port: int = DEFAULT_PORT) -> dict:
    """Configures settings.json with AgentP settings for Cursor according to platform."""
    plat = get_platform()
    home = Path.home()
    base_url = f"http://127.0.0.1:{port}/v1"
    
    if plat == "windows":
        appdata = os.environ.get("APPDATA")
        cursor_dir = Path(appdata) / "Cursor" / "User" if appdata else home / "AppData" / "Roaming" / "Cursor" / "User"
    elif plat == "macos":
        cursor_dir = home / "Library" / "Application Support" / "Cursor" / "User"
    else:  # linux
        cursor_dir = home / ".config" / "cursor" / "User"
        
    target_path = cursor_dir / "settings.json"
    data = _safe_load_json(target_path)
    data["cursor.openai.baseUrl"] = base_url
    data["cursor.openai.apiKey"] = DEFAULT_DUMMY_KEY
    _safe_save_json(target_path, data)
    
    return {
        "agent": "Cursor",
        "status": "success",
        "file": str(target_path),
        "endpoint": base_url,
        "gui_tip": "Keep 'Override OpenAI Base URL' enabled in Cursor Settings > Models tab."
    }


def configure_antigravity(port: int = DEFAULT_PORT) -> dict:
    """Configures settings.json for Antigravity CLI/IDE."""
    home = Path.home()
    target_path = home / ".gemini" / "antigravity-cli" / "settings.json"
    base_url = f"http://127.0.0.1:{port}/v1"
    
    data = _safe_load_json(target_path)
    data["openai_base_url"] = base_url
    data["openai_api_key"] = DEFAULT_DUMMY_KEY
    _safe_save_json(target_path, data)
    
    # Also set AGENTP_PROXY_URL if .env exists in current working directory
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        if "AGENTP_PROXY_URL" not in content:
            with env_file.open("a", encoding="utf-8") as f:
                f.write(f"\nAGENTP_PROXY_URL={base_url}\n")
                
    return {
        "agent": "Antigravity",
        "status": "success",
        "file": str(target_path),
        "endpoint": base_url
    }


def configure_all(port: int = DEFAULT_PORT, model_id: str = "nvidia/nemotron-3.5-lightning-30b-a3b") -> list:
    """Configures all supported coding agents in a single step."""
    results = [
        configure_opencode(port=port, model_id=model_id),
        configure_claude_code(port=port),
        configure_cursor(port=port),
        configure_antigravity(port=port)
    ]
    return results
