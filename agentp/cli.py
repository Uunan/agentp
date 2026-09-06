"""AgentP - Interactive CLI and Management Interface."""
import argparse
import os
import sys
from pathlib import Path
import uvicorn

from .config import load_config, load_model_config, save_config, ROOT
from .installer import (
    configure_opencode,
    configure_claude_code,
    configure_cursor,
    configure_antigravity,
    configure_all,
    get_platform
)

# ANSI Color Palette (Perry the Platypus & Cyberpunk Agent Theme)
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[38;2;0;229;255m"
CYAN_BOLD = "\033[38;2;0;229;255;1m"
TEAL = "\033[38;2;38;166;154m"      # Perry Teal
FEDORA = "\033[38;2;178;89;45m"     # Fedora Brown
BAND = "\033[38;2;55;55;65;1m"      # Hat Band
ORANGE = "\033[38;2;255;138;30m"    # Bill Orange
GREEN = "\033[38;2;0;230;118m"      # Success Green
YELLOW = "\033[38;2;255;215;64m"    # Yellow Accent
PURPLE = "\033[38;2;186;104;200m"   # Purple Accent
GRAY = "\033[38;2;144;164;174m"     # Gray
WHITE = "\033[97;1m"                # Pure bright white

# Enable UTF-8 and ANSI support on Windows console
if sys.platform.startswith("win"):
    os.system("")
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

PERRY_ASCII = r"""                              %#%
                           %%%%%%#
                        [%%%%%%%%%%
                      }%%%%%%%%%%%%%
               #%%%%%%%%%%%%%%%%%##%%
              %%%%%%%%%%%%%{{{#####{%
              %%%%%%%%%{{{###%%%{###{#
              [%%%%{{#{{{{#%%%%%%%%%%%%%%%%%%%%%%%%
           %#%%%%%%%#%%%%%#%%%%%%%%%%%%%%%%%[
      #%%%%%%%%%%%%#{{{{{{{{{{{{#{{{#{%%%{
      %%%%%%%%%%{{{{%]%#     {{{{%{%%    %
       %%%%%%%%%{{{{%       }{{{{%###%%#
           %%#%#{{{{{{{##%#{{{{###{{{{%
               [{{{{{{{{{{{{{%#####%%{########%}
                {{{{{{{{{{{##################%%
                {{{{{{{{%####%%########%
                #{{{{{{{%##########%%{{%
                %{{{{{{{{{{##%%#{{{{{{{{
                %{{{{{{{{{{{{{{{{{{{{{{%
                %{{{{{{{{{{{{{{{{{{{{{{%
                %{{{{{{{{{{{{{{{{{{{{{{}
                #{{{{{{{{{{{{{{{{{{{{{%
                 [%{{{{{{{{{{{{{{{{#%
                       %#%%%%%%%%["""


def load_ascii_art() -> str:
    """Returns Perry the Platypus ASCII art in pure white."""
    raw_lines = [l.rstrip() for l in PERRY_ASCII.splitlines() if l.strip()]
    return "\n".join(f"{WHITE}{line}{RESET}" for line in raw_lines)


def load_combined_banner() -> str:
    """Returns ASCII art banner."""
    return load_ascii_art()


def _prompt(text: str, default: str = "") -> str:
    """Prompt user for input, defaulting if left empty."""
    default_str = f" {GRAY}[{default}]{RESET}" if default else ""
    try:
        val = input(f"{CYAN}{text}{default_str}{CYAN}: {RESET}").strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{YELLOW}Cancelled.{RESET}")
        sys.exit(0)
    return val if val else default


def setup_wizard(force: bool = False):
    """Initial setup wizard: configure endpoint, api key, model and coding agent integrations."""
    os.system("")
    banner = load_combined_banner()
    print(banner)
    print()

    print(f"{YELLOW}{BOLD}╭────────────────────────────────────────────────────────────╮{RESET}")
    print(f"{YELLOW}{BOLD}│             🕵️‍♂️  AGENT P INITIAL SETUP WIZARD             │{RESET}")
    print(f"{YELLOW}{BOLD}╰────────────────────────────────────────────────────────────╯{RESET}")
    print(f"{GRAY}Configure your upstream LLM connection and coding agent integrations.\n{RESET}")

    cfg = load_config()
    up = cfg.get("upstream", {})
    srv = cfg.get("server", {})

    cur_base = up.get("base_url", "https://integrate.api.nvidia.com/v1")
    cur_env_key = up.get("api_key_env", "NVIDIA_API_KEY")
    cur_api_key = os.environ.get(cur_env_key, "")
    cur_model = up.get("model", "nvidia/nemotron-3.5-lightning-30b-a3b")
    cur_port = str(srv.get("port", 8000))

    base_url = _prompt("[1/4] Upstream Base URL", cur_base)
    api_key = _prompt("[2/4] Upstream API Key (Secret Key)", cur_api_key or "sk-...")
    model_name = _prompt("[3/4] Upstream Model Name", cur_model)
    port_str = _prompt("[4/4] Local Proxy Port", cur_port)
    port = int(port_str) if port_str.isdigit() else 8000

    # Update config
    cfg["server"]["port"] = port
    cfg["upstream"]["base_url"] = base_url
    cfg["upstream"]["model"] = model_name
    save_config(cfg)

    # Save to .env
    env_file = ROOT / ".env"
    env_lines = []
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(f"{cur_env_key}="):
                env_lines.append(line)
    env_lines.append(f"{cur_env_key}={api_key}")
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    os.environ[cur_env_key] = api_key

    print(f"\n{GREEN}✔ Upstream and server configuration saved successfully.{RESET}")

    # Code agent integration choice
    plat = get_platform()
    w = 64
    print(f"\n{CYAN}╭{'─' * (w - 2)}╮{RESET}")
    print(f"{CYAN}│{RESET}  {BOLD}Which code agent would you like to connect AgentP with?{RESET}   {CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {GRAY}(Detected Platform: {plat.upper()}){RESET}" + " " * (w - 23 - len(plat)) + f"{CYAN}│{RESET}")
    print(f"{CYAN}├{'─' * (w - 2)}┤{RESET}")
    print(f"{CYAN}│{RESET}  {ORANGE}[1]{RESET} {WHITE}OpenCode    {RESET} {GRAY}(~/.config/opencode/opencode.json){RESET}      {CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {ORANGE}[2]{RESET} {WHITE}Cursor      {RESET} {GRAY}(User/settings.json){RESET}                    {CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {ORANGE}[3]{RESET} {WHITE}Claude Code {RESET} {GRAY}(~/.claude/settings.json){RESET}               {CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {ORANGE}[4]{RESET} {WHITE}Antigravity {RESET} {GRAY}(~/.gemini/antigravity-cli/...){RESET}         {CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {GREEN}[5]{RESET} {GREEN}{BOLD}INSTALL ALL {RESET} {YELLOW}★ Recommended (Configures all){RESET}          {CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {GRAY}[0]{RESET} {GRAY}Skip        (Start proxy server only){RESET}               {CYAN}│{RESET}")
    print(f"{CYAN}╰{'─' * (w - 2)}╯{RESET}")

    choice = _prompt("Your choice [1-5 / 0]", "5")

    def _print_res(res):
        print(f"  {GREEN}✔ [{res['agent']}]{RESET} Configured: {WHITE}{res['file']}{RESET}")
        if "gui_tip" in res:
            print(f"    {GRAY}Tip: {res['gui_tip']}{RESET}")

    if choice == "1":
        r = configure_opencode(port=port, model_id=model_name)
        _print_res(r)
    elif choice == "2":
        r = configure_cursor(port=port)
        _print_res(r)
    elif choice == "3":
        r = configure_claude_code(port=port)
        _print_res(r)
    elif choice == "4":
        r = configure_antigravity(port=port)
        _print_res(r)
    elif choice == "5":
        results = configure_all(port=port, model_id=model_name)
        for r in results:
            _print_res(r)
    else:
        print(f"  {YELLOW}Agent integration skipped.{RESET}")

    print(f"\n{GREEN}{BOLD}🎉 Setup complete! Agent P is ready for duty...{RESET}\n")


def start_proxy(host: str = None, port: int = None):
    """Starts the proxy server with Perry the Platypus banner and status dashboard."""
    os.system("")
    cfg = load_config()
    mc = load_model_config()
    srv = cfg.get("server", {})
    up = cfg.get("upstream", {})

    h = host or srv.get("host", "127.0.0.1")
    p = port or int(srv.get("port", 8000))

    # 1. Logo and ASCII Art
    banner = load_combined_banner()
    print(banner)
    print()

    # 2. Modern Dashboard Card
    w = 76
    h_str = f"http://{h}:{p}/v1"
    claude_str = f"http://{h}:{p}"
    base_str = up.get("base_url", "")
    model_str = up.get("model", "nvidia/nemotron-3.5-lightning-30b-a3b")
    active_str = f"{mc.get('active_model')} (PyTorch HuggingFace)"
    roles_str = ", ".join(mc.get("scan_roles", []))

    print(f"{CYAN}╭{'─' * (w - 2)}╮{RESET}")
    print(f"{CYAN}│{RESET}  {BOLD}STATUS:{RESET} {GREEN}● ACTIVE & PROTECTED{RESET}" + " " * 22 + f"{GRAY}AGENCY: {YELLOW}O.W.C.A.{RESET} {CYAN}│{RESET}")
    print(f"{CYAN}├{'─' * (w - 2)}┤{RESET}")
    print(f"{CYAN}│{RESET}  {ORANGE}🛡️  Local Proxy URL   {RESET}: {WHITE}{h_str:<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {ORANGE}🎩  Claude Code URL   {RESET}: {WHITE}{claude_str:<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {TEAL}🎯  Upstream Target   {RESET}: {GRAY}{base_str:<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {TEAL}🧠  Upstream Model    {RESET}: {WHITE}{model_str:<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {YELLOW}🔍  Active NER Engine {RESET}: {WHITE}{active_str:<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {YELLOW}🏷️   Scanned Roles     {RESET}: {GRAY}{roles_str:<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}│{RESET}  {GREEN}⚡  Protected Agents  {RESET}: {GREEN}{'OpenCode • Claude Code • Cursor • Antigravity':<50}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}╰{'─' * (w - 2)}╯{RESET}")
    print()
    print(f"  {YELLOW}🕵️‍♂️  \"A platypus? ... A HAT?! ... PERRY THE PLATYPUS?!\"{RESET}")
    print(f"  {DIM}To stop the server: Ctrl + C{RESET}\n")

    uvicorn.run("agentp.proxy:app", host=h, port=p, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="AgentP - Local PII Redaction & Fake-Swap Privacy Proxy")
    parser.add_argument("--setup", action="store_true", help="Runs the interactive setup wizard")
    parser.add_argument("--install", choices=["all", "opencode", "cursor", "claude", "antigravity"],
                        help="Automatically installs integration for the specified code agent")
    parser.add_argument("--port", type=int, help="Sets the server port")
    parser.add_argument("--host", type=str, help="Sets the server host address")
    parser.add_argument("--check", action="store_true", help="Runs the local model smoke test")

    args = parser.parse_args()

    if args.check:
        from .main import check
        check()
        return

    cfg = load_config()
    up = cfg.get("upstream", {})
    api_key_env = up.get("api_key_env", "NVIDIA_API_KEY")
    api_key = os.environ.get(api_key_env, "")

    if args.install:
        p = args.port or int(cfg.get("server", {}).get("port", 8000))
        m = up.get("model", "nvidia/nemotron-3.5-lightning-30b-a3b")
        if args.install == "all":
            for r in configure_all(port=p, model_id=m):
                print(f"[{r['agent']}] OK: {r['file']}")
        elif args.install == "opencode":
            r = configure_opencode(port=p, model_id=m)
            print(f"[{r['agent']}] OK: {r['file']}")
        elif args.install == "cursor":
            r = configure_cursor(port=p)
            print(f"[{r['agent']}] OK: {r['file']}")
        elif args.install == "claude":
            r = configure_claude_code(port=p)
            print(f"[{r['agent']}] OK: {r['file']}")
        elif args.install == "antigravity":
            r = configure_antigravity(port=p)
            print(f"[{r['agent']}] OK: {r['file']}")
        return

    # If --setup or api_key not yet configured, launch wizard
    if args.setup or not api_key:
        setup_wizard()

    start_proxy(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
