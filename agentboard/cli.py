"""CLI for Agent Session Workboard.

The web UI is the primary surface; these commands cover setup and quick
terminal-side actions (list / send / new / kill / summarize).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentboard import __version__
from agentboard.config import (
    Config,
    get_default_config_path,
    init_config,
    load_config,
)
from agentboard.core.sessions import SessionRegistry
from agentboard.core.tmux import Tmux, TmuxError
from agentboard.logging import get_logger

app = typer.Typer(
    name="agentboard",
    help="Agent Session Workboard — drive your local & remote agent sessions from anywhere.",
    add_completion=False,
)
console = Console()
logger = get_logger(__name__)

ConfigOpt = Annotated[str | None, typer.Option("--config", "-c", help="Config file path")]


@app.command()
def init(
    config_path: ConfigOpt = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing config")] = False,
) -> None:
    """Create the config file and data directory."""
    cp = init_config(config_path, force=force)
    cfg = load_config(cp)
    from pathlib import Path

    Path(cfg.workspace.data_dir).expanduser().mkdir(parents=True, exist_ok=True)
    console.print("[green]✓[/green] Initialized.")
    console.print(f"  Config: {cp}")
    console.print("\n[bold]Next:[/bold]")
    console.print("  agentboard sessions       # list agent sessions")
    console.print("  agentboard web            # start the web hub (local)")
    console.print("  agentboard web --remote   # expose with a bearer token")


@app.command("sessions")
def list_sessions(config_path: ConfigOpt = None) -> None:
    """List agent sessions across all configured machines."""
    cfg = load_config(config_path)
    registry = SessionRegistry(cfg.machines)
    sessions = registry.list(refresh=True)
    if not sessions:
        console.print("[dim]No tmux sessions found on any machine.[/dim]")
        return
    table = Table(title="Agent Sessions")
    table.add_column("Machine")
    table.add_column("Session")
    table.add_column("CLI")
    table.add_column("Agent")
    table.add_column("Directory", overflow="fold")
    for s in sessions:
        table.add_row(
            s.machine,
            s.name,
            s.cli,
            "✓" if s.is_agent else "",
            s.cwd,
        )
    console.print(table)


@app.command()
def send(
    machine: Annotated[str, typer.Argument(help="Machine name")],
    name: Annotated[str, typer.Argument(help="tmux session name")],
    message: Annotated[list[str] | None, typer.Argument(help="Message text")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Send a message to a session's agent (types it + Enter)."""
    cfg = load_config(config_path)
    if not message:
        console.print("[red]No message given.[/red]")
        raise typer.Exit(1)
    tmux = _tmux_for(cfg, machine)
    try:
        tmux.send(name, " ".join(message), enter=True)
        console.print("[green]✓ sent[/green]")
    except TmuxError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def new(
    machine: Annotated[str, typer.Argument(help="Machine name")],
    cwd: Annotated[str, typer.Argument(help="Working directory")],
    command: Annotated[str, typer.Option("--command", help="Agent command")] = "codex",
    name: Annotated[str | None, typer.Option("--name", help="tmux session name")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Start a new agent session in a fresh tmux session."""
    cfg = load_config(config_path)
    tmux = _tmux_for(cfg, machine)
    sess_name = name or f"{cwd.rstrip('/').split('/')[-1] or 'agent'}-{command.split()[0]}"
    try:
        tmux.new_session(sess_name, cwd, command)
        console.print(f"[green]✓ created[/green] {machine}/{sess_name}")
    except TmuxError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def kill(
    machine: Annotated[str, typer.Argument(help="Machine name")],
    name: Annotated[str, typer.Argument(help="tmux session name")],
    config_path: ConfigOpt = None,
) -> None:
    """Kill a session (ends the agent process)."""
    cfg = load_config(config_path)
    tmux = _tmux_for(cfg, machine)
    try:
        tmux.kill_session(name)
        console.print("[green]✓ killed[/green]")
    except TmuxError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def summarize(
    machine: Annotated[str | None, typer.Option("--machine", "-m")] = None,
    name: Annotated[str | None, typer.Option("--name", "-n")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Generate LLM summary cards for sessions (all, or one with -m/-n)."""
    cfg = load_config(config_path)
    if not (cfg.llm.api_key or _env_key(cfg)):
        console.print("[red]No LLM API key configured.[/red]")
        raise typer.Exit(1)
    registry = SessionRegistry(cfg.machines)
    sessions = [s for s in registry.list(refresh=True) if s.is_agent]
    if machine:
        sessions = [s for s in sessions if s.machine == machine]
    if name:
        sessions = [s for s in sessions if s.name == name]
    if not sessions:
        console.print("[dim]No matching agent sessions.[/dim]")
        return

    from agentboard.core.transcript import local_transcript_for, parse_screen
    from agentboard.intelligence.summary import summarize_session

    async def run() -> int:
        done = 0
        for s in sessions:
            state = None
            if s.machine_type == "local":
                mc = next((m for m in cfg.machines if m.name == s.machine), None)
                state = local_transcript_for(
                    s.cwd, s.cli,
                    codex_home=(mc.codex_home if mc else None) or "~/.codex",
                    claude_home=(mc.claude_home if mc else None) or "~/.claude",
                )
            if state is None or not state.messages:
                tmux = registry.tmux_for(s.machine)
                state = parse_screen(tmux.capture(s.name, 400) if tmux else "")
            card = await summarize_session(cfg, s.key, state, force=True)
            if card:
                done += 1
                console.print(f"  [green]✓[/green] {s.key} — {card.title}")
            else:
                console.print(f"  [dim]○[/dim] {s.key} (skipped)")
        return done

    n = asyncio.run(run())
    console.print(f"\n[green]Summarized {n}/{len(sessions)}.[/green]")


@app.command()
def web(
    port: Annotated[int, typer.Option("--port", "-p")] = 8765,
    remote: Annotated[bool, typer.Option("--remote", help="Expose externally with auth")] = False,
    config_path: ConfigOpt = None,
) -> None:
    """Start the web hub."""
    import uvicorn

    from agentboard.auth.middleware import load_or_create_token
    from agentboard.web.app import create_app

    cfg = load_config(config_path)
    if remote:
        cfg.remote.enabled = True
        cfg.auth.enabled = True

    if cfg.remote.enabled and cfg.auth.enabled:
        config_file = config_path or str(get_default_config_path())
        token = load_or_create_token(cfg.auth, config_file)
        bind = cfg.remote.bind_host
        console.print("[bold yellow]🔐 Remote access enabled[/bold yellow]")
        console.print(f"  Bind:  {bind}:{port}")
        _print_access(token, port)
        if not _tailscale_ip():
            console.print("  [dim]Different networks? Install Tailscale here + on your phone "
                          "for a stable cross-network address.[/dim]")
        console.print()
    else:
        bind = "127.0.0.1"
        console.print(f"[green]Web hub at http://{bind}:{port}[/green]")
        console.print("[dim]Local only. Use --remote to expose with a bearer token.[/dim]")

    app_instance = create_app(cfg)
    uvicorn.run(app_instance, host=bind, port=port, log_level="info")


@app.command()
def token(
    rotate: Annotated[bool, typer.Option("--rotate", help="Generate a new token")] = False,
    port: Annotated[int, typer.Option("--port", "-p", help="Port for the access URL")] = 8765,
    config_path: ConfigOpt = None,
) -> None:
    """Show the bearer token + access URLs (and a scannable QR), or rotate it."""
    from agentboard.auth.middleware import (
        _save_token_to_config,
        generate_token,
        load_or_create_token,
    )

    cfg = load_config(config_path)
    config_file = config_path or str(get_default_config_path())
    if rotate:
        tok = generate_token()
        cfg.auth.bearer_token = tok
        try:
            _save_token_to_config(config_file, tok)
            console.print("[green]✓ New token generated and saved.[/green] "
                          "The old one no longer works.")
        except Exception as e:  # noqa: BLE001 — best-effort write; token still printed
            console.print(f"[yellow]Generated, but could not write config ({e}). "
                          f"Set auth.bearer_token manually.[/yellow]")
        console.print("[dim]Restart a running server for the new token to take effect.[/dim]")
    else:
        tok = load_or_create_token(cfg.auth, config_file)
    console.print("[bold]🔑 Access[/bold]")
    _print_access(tok, port)


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"agentboard v{__version__}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmux_for(cfg: Config, machine: str) -> Tmux:
    mc = next((m for m in cfg.machines if m.name == machine), None)
    if mc is None:
        console.print(f"[red]Unknown machine: {machine}[/red]")
        raise typer.Exit(1)
    return Tmux(mc.host if mc.type == "ssh" else None)


def _env_key(cfg: Config) -> str:
    import os

    return os.environ.get(cfg.llm.api_key_env, "")


def _tailscale_ip() -> str | None:
    """The machine's Tailscale IPv4, if Tailscale is installed and up."""
    import subprocess

    for cmd in (["tailscale", "ip", "-4"],
                ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "ip", "-4"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0].strip()
    return None


def _lan_ip() -> str | None:
    """Best-effort primary LAN IP (for same-network access)."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        return None
    # 198.18.0.0/15 is the range Clash/mihomo TUN hands out for fake-ip — not a
    # real LAN address, so don't advertise it as a same-network URL.
    if ip.startswith(("198.18.", "198.19.")):
        return None
    return ip


def _access_urls(token: str, port: int) -> list[tuple[str, str]]:
    """Labelled access URLs, best (cross-network) first."""
    urls: list[tuple[str, str]] = []
    ts = _tailscale_ip()
    if ts:
        urls.append(("Cross-network URL (Tailscale)", f"http://{ts}:{port}/?token={token}"))
    lan = _lan_ip()
    if lan:
        urls.append(("Same-network URL (LAN)", f"http://{lan}:{port}/?token={token}"))
    return urls


def _print_qr(url: str) -> None:
    """Print a scannable ASCII QR for an access URL (graceful if qrcode absent)."""
    try:
        import io

        import qrcode
    except ImportError:
        console.print("  [dim](install 'qrcode' to show a scannable QR)[/dim]")
        return
    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf)
    console.print(buf.getvalue())


def _print_access(token: str, port: int) -> None:
    """Print the token, access URLs, and a QR of the best URL to scan from a phone."""
    console.print(f"  Token: [bold green]{token}[/bold green]")
    urls = _access_urls(token, port)
    for label, url in urls:
        console.print(f"  {label}: [green]{url}[/green]")
    primary = urls[0][1] if urls else f"http://127.0.0.1:{port}/?token={token}"
    _print_qr(primary)
    console.print("  [dim]📱 Scan the QR to log in on your phone "
                  "(saved as a cookie for 30 days).[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
