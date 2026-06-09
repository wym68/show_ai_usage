"""SHOW AI USAGE — CLI entry point for the subscription data poller."""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path so that ``poller.*`` imports work
# when the script is invoked directly (``python poller/main.py``).
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from poller.browser import BROWSER_DATA_DIR, ManagedBrowser
from poller.config import CONFIG_FILE, init_default_config, load_config, merge_cli_overrides
from poller.storage import load_results, save_results

_running = True


def _signal_handler(signum: int, _frame: object) -> None:
    global _running
    print(f"\n  Caught signal {signum}, shutting down gracefully...")
    _running = False


def _print_banner() -> None:
    print(r"  ┌─┐ ┌─┐┬ ┬ ┬ ┌─┐  ┌─┐ ┬ ┬ ┌┐ ┌─┐┌─┐┌─┐")
    print(r"  ├┤  │  │ └┬┘ ├┤   ├─┘ └┬┘ ├┴┐├─┘├─┘└─┐")
    print(r"  └─┘ └─┘┴─┘┴ └─┘  ┴    ┴  └─┘┴  ┴  └─┘")
    print("  AI Subscription Usage Monitor for KDE Plasma 6\n")


LOGIN_URLS: dict[str, str] = {
    "codex":   "https://chatgpt.com",
    "claude":  "https://claude.ai",
    "kimi":    "https://www.kimi.com",
    "minimax": "https://platform.minimaxi.com",
}


def _get_browser_data_dir(config_path: str) -> Path:
    """Resolve the effective browser data directory from config or default."""
    if config_path:
        return Path(config_path).expanduser().resolve()
    return BROWSER_DATA_DIR


def _handle_login(config, provider: str = "codex") -> None:
    """Open the isolated browser for manual login to a provider."""
    login_url = LOGIN_URLS.get(provider)
    if not login_url:
        print(f"✗ Unknown provider '{provider}'. Available: {', '.join(sorted(LOGIN_URLS))}")
        return

    display_name = {"codex": "OpenAI Codex", "claude": "Claude", "kimi": "Kimi", "minimax": "MiniMax"}

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    print("[1/3] Starting isolated Edge browser (project profile) ...")
    print(f"      Profile: {browser_dir}")

    with ManagedBrowser(headless=False, data_dir=browser_dir) as browser:
        context = browser.get_context()
        page = context.new_page()

        print(f"\n[2/3] Navigating to {login_url} ...")
        page.goto(
            login_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(2000)

        print(f"\n╔══════════════════════════════════════════════════════════════╗")
        print(f"║  Please log in to {display_name.get(provider, provider)} in the browser window.  ║")
        print(f"║  This profile is completely isolated from your system       ║")
        print(f"║  browser — nothing is shared.                              ║")
        print(f"║                                                            ║")
        print(f"║  Once logged in, come back here and press [Enter] to save.  ║")
        print(f"╚══════════════════════════════════════════════════════════════╝")
        input()

        page.close()
        print(f"\n[3/3] ✓ Profile saved. You can now run `--oneshot --providers {provider}`.\n")


def _poll(provider_names: list[str], config) -> list[dict]:
    """Shared logic: open browser, poll providers, return results list."""
    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    if not browser_dir.exists():
        print("✗ No browser profile found. Run `--login` first.")
        sys.exit(1)

    from poller.providers import get_enabled_providers

    providers = get_enabled_providers(provider_names)

    if not providers:
        print("  (no providers enabled)")
        return []

    results: list[dict] = []
    with ManagedBrowser(headless=True, data_dir=browser_dir) as browser:
        context = browser.get_context()
        for provider in providers:
            print(f"  Polling {provider.name} ...", end=" ", flush=True)
            try:
                data = provider.fetch(context)
                results.append(data.model_dump(mode="json"))
                print(
                    f"✓  5h={data.window_5h_percent:.0f}%  "
                    f"7d={data.window_7d_percent:.0f}%"
                )
            except Exception as exc:
                results.append(
                    {
                        "provider": provider.name,
                        "error": str(exc),
                        "window_5h_percent": None,
                        "window_7d_percent": None,
                    }
                )
                print(f"✗  {exc}")
            # Small delay between providers to let Playwright fully clean up pages
            import time as _time
            _time.sleep(1)
    return results


def _handle_oneshot(provider_names: list[str], config) -> None:
    """Run a single poll cycle and write results to disk."""
    results = _poll(provider_names, config)
    if results:
        save_results(results, data_dir=config.data_dir)
        print(f"\nResults written to storage ({len(results)} providers).")
    else:
        print("\nNothing to save.")


def _handle_debug_dump(provider_names: list[str], config) -> None:
    """Open each provider's dashboard in a headed browser and dump the page content."""
    print("=== DEBUG MODE: dumping page content ===\n")

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    if not browser_dir.exists():
        print("✗ No browser profile found. Run `--login` first.")
        sys.exit(1)

    PROVIDER_URLS: dict[str, str] = {
        "codex":   "https://chatgpt.com/codex/cloud/settings/analytics",
        "claude":  "https://claude.ai/new#settings/usage",
        "kimi":    "https://www.kimi.com/code/console",
        "minimax": "https://platform.minimaxi.com/console/usage",
    }

    from poller.providers import get_enabled_providers

    providers = get_enabled_providers(provider_names)
    dump_dir = Path("/tmp/show-ai-usage-debug")
    dump_dir.mkdir(parents=True, exist_ok=True)

    with ManagedBrowser(headless=False, data_dir=browser_dir) as browser:
        context = browser.get_context()

        for provider in providers:
            url = PROVIDER_URLS.get(provider.name)
            if not url:
                print(f"\n✗ No debug URL configured for {provider.name}")
                continue

            print(f"\n--- {provider.name} -> {url} ---")
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                print("  Waiting for page to render (up to 45s)...")
                for _ in range(30):
                    title = page.title()
                    if title not in {"请稍候…", "Just a moment...", "Please wait...", ""}:
                        break
                    time.sleep(1.5)
                page.wait_for_timeout(5000)

                html = page.content()
                (dump_dir / f"{provider.name}.html").write_text(html)
                text = page.evaluate("document.body?.innerText || ''")
                (dump_dir / f"{provider.name}.txt").write_text(text)
                page.screenshot(path=str(dump_dir / f"{provider.name}.png"))
                print(f"  → Saved: {dump_dir}/{provider.name}.{{html,txt,png}}")
                print(f"  → Page title: {page.title()}")
                print(f"  → Body text length: {len(text)} chars")

                if text.strip():
                    try:
                        data = provider.fetch(context)
                        print(f"  → Parse result: {data.model_dump_json()}")
                    except Exception as exc:
                        print(f"  → Parse failed: {exc}")
                else:
                    print("  → Body empty — page likely still loading or blocked.")
            except Exception as e:
                print(f"  → Error: {e}")
            finally:
                page.close()


def _handle_daemon(provider_names: list[str], config) -> None:
    """Run in a loop, polling providers every *config.interval* seconds."""
    import signal as _signal

    _signal.signal(_signal.SIGINT, _signal_handler)
    _signal.signal(_signal.SIGTERM, _signal_handler)

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    if not browser_dir.exists():
        print("✗ No browser profile found. Run `--login` first.")
        sys.exit(1)

    interval = config.interval

    print(f"Daemon started — polling {len(provider_names)} provider(s) every {interval}s")
    print(f"  Config: {CONFIG_FILE}")
    print("  Press Ctrl+C to stop.\n")

    while _running:
        cycle_start = time.time()
        print(f"[{datetime.now():%H:%M:%S}] Polling ...", end=" ", flush=True)
        results = _poll(provider_names, config)
        if results:
            save_results(results, data_dir=config.data_dir)
        elapsed = time.time() - cycle_start
        sleep = max(0, interval - elapsed)
        if _running and sleep > 0:
            time.sleep(sleep)
        print(f"({elapsed:.0f}s)")

    print("Daemon stopped.")


def _handle_status(config, json_output: bool = False) -> None:
    """Display the most recently cached poll results."""
    data = load_results(data_dir=config.data_dir)
    if data is None:
        print("No data available yet. Run `--oneshot` first.")
        return

    if json_output:
        import json as _json
        print(_json.dumps(data, indent=2, ensure_ascii=False))
        return

    fetched_str = data.get("fetched_at", "unknown")
    try:
        fetched_dt = datetime.fromisoformat(fetched_str)
        age = datetime.now(timezone.utc) - fetched_dt
        age_str = f"{int(age.total_seconds())}s ago"
    except (ValueError, TypeError):
        age_str = "unknown"

    print(f"Last fetched: {fetched_str}  ({age_str})")
    print()

    for prov in data.get("providers", []):
        name = prov.get("provider", "?")
        err = prov.get("error")
        if err:
            print(f"  {name}: ✗ {err}")
            continue

        p5 = prov.get("window_5h_percent")
        p7 = prov.get("window_7d_percent")
        credit = prov.get("remaining_credit")
        reset = prov.get("reset_in")

        print(f"  {name}")
        print(f"    5h: {p5:.0f}%" if p5 is not None else "    5h: N/A")
        print(f"    7d: {p7:.0f}%" if p7 is not None else "    7d: N/A")
        if credit is not None:
            print(f"    剩余额度: {credit}")
        if reset is not None:
            print(f"    重置: {reset}")
        print()


def cli() -> None:
    _print_banner()

    parser = argparse.ArgumentParser(
        description="Poll AI subscription usage data from provider dashboards.",
    )
    parser.add_argument(
        "--login",
        type=str,
        nargs="?",
        const="codex",
        default=None,
        metavar="PROVIDER",
        help="Open the isolated browser for manual login. Optionally specify a provider: codex, claude, kimi, minimax (default: codex).",
    )
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Run a single poll cycle and write results to disk.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run in debug mode (headed browser) and dump page content for analysis.",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon, polling at the given interval.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display the most recent cached poll data.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output data as JSON (use with --status).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Polling interval in seconds (overrides config file).",
    )
    parser.add_argument(
        "--providers",
        type=str,
        nargs="*",
        help="Specific providers to poll (overrides config file).",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Write a default config.toml with comments and exit.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the effective configuration and exit.",
    )

    args = parser.parse_args()

    # ── Config-free commands ──────────────────────────────────────
    if args.init_config:
        path = init_default_config()
        print(f"Default config written to:\n  {path}\n")
        print("Edit it to customise providers, interval, etc.")
        return

    # ── Load config & merge CLI overrides ─────────────────────────
    cfg = load_config()
    cfg = merge_cli_overrides(
        cfg,
        interval=args.interval,
        providers=args.providers,
    )

    if args.show_config:
        print(cfg.model_dump_json(indent=2))
        return

    # ── Resolve which providers will be used ──────────────────────
    provider_names = args.providers if args.providers else cfg.enabled_providers

    # ── Dispatch ──────────────────────────────────────────────────
    if args.login:
        _handle_login(cfg, provider=args.login)
        return

    if args.debug:
        _handle_debug_dump(provider_names, cfg)
        return

    if args.oneshot:
        _handle_oneshot(provider_names, cfg)
        return

    if args.daemon:
        _handle_daemon(provider_names, cfg)
        return

    if args.status:
        _handle_status(cfg, json_output=args.json_output)
        return

    parser.print_help()


if __name__ == "__main__":
    cli()
