"""SHOW AI USAGE — CLI entry point for the subscription data poller."""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from poller.logger import get_logger, setup_logging

# Ensure the project root is on sys.path so that ``poller.*`` imports work
# when the script is invoked directly (``python poller/main.py``).
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from poller.browser import BROWSER_DATA_DIR, ManagedBrowser, get_system_timezone
from poller.config import CONFIG_FILE, init_default_config, load_config, merge_cli_overrides
from poller.storage import load_results, save_results

log = get_logger(__name__)

_running = True


def _signal_handler(signum: int, _frame: object) -> None:
    global _running
    log.warning("Caught signal %d, shutting down gracefully...", signum)
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

# Per-provider config field that gates the direct-API fetch path.
_DIRECT_FETCH_FLAGS: dict[str, str] = {
    "claude":  "claude_use_direct_fetch",
    "kimi":    "kimi_use_direct_fetch",
    "minimax": "minimax_use_direct_fetch",
}


def _get_browser_data_dir(config_path: str) -> Path:
    """Resolve the effective browser data directory from config or default."""
    if config_path:
        return Path(config_path).expanduser().resolve()
    return BROWSER_DATA_DIR


def _wait_for_browser_close(context, *, max_wait: int = 900) -> None:
    """Block until the user closes the browser, or ``max_wait`` seconds elapse.

    Used for GUI-launched logins where there is no stdin to wait on. Polls
    the persistent context's open pages; once they are all closed (the user
    closed the window) the login state has already been persisted to the
    profile directory by Chromium.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            if not context.pages:
                return
        except Exception:
            # Context went away (browser closed) — treat as done.
            return
        time.sleep(1.0)
    log.warning("Login wait timed out after %ds; saving whatever state exists.", max_wait)


def _handle_login(config, provider: str = "codex") -> None:
    """Open the isolated browser for manual login to a provider."""
    login_url = LOGIN_URLS.get(provider)
    if not login_url:
        log.error("Unknown provider '%s'. Available: %s", provider, ", ".join(sorted(LOGIN_URLS)))
        return

    display_name = {"codex": "OpenAI Codex", "claude": "Claude", "kimi": "Kimi", "minimax": "MiniMax"}

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    resolved_timezone = config.timezone or get_system_timezone()
    log.info("Starting isolated Edge browser (profile: %s)", browser_dir)

    with ManagedBrowser(headless=False, data_dir=browser_dir, timezone=resolved_timezone) as browser:
        context = browser.get_context()
        page = context.new_page()

        log.info("Navigating to %s ...", login_url)
        page.goto(
            login_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(2000)

        name = display_name.get(provider, provider)
        if sys.stdin.isatty():
            # Interactive terminal: wait for the user to press Enter.
            print(f"\n╔══════════════════════════════════════════════════════════════╗")
            print(f"║  Please log in to {name} in the browser window.")
            print(f"║  This profile is isolated from your system browser.")
            print(f"║  Once logged in, return here and press [Enter] to save.")
            print(f"╚══════════════════════════════════════════════════════════════╝")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        else:
            # Launched without a terminal (e.g. from the widget): there is no
            # stdin to read, so wait until the user closes the browser window.
            log.info(
                "Please log in to %s in the browser window, then close it to save.",
                name,
            )
            _wait_for_browser_close(context)

        page.close()
        log.info("Profile saved. You can now run --oneshot --providers %s.", provider)


def _handle_set_token(provider: str) -> None:
    """Securely prompt for a provider credential and write it to secrets.env.

    The token is read with ``getpass`` (never echoed, never placed on the
    command line) and stored in ``~/.config/show-ai-usage/secrets.env`` at
    mode 0600 — the single source of truth for credentials.
    """
    import getpass

    from poller.config import SECRET_ENV_BY_PROVIDER, write_secret

    env_var = SECRET_ENV_BY_PROVIDER.get(provider)
    if env_var is None:
        log.error(
            "Provider '%s' has no direct-API credential. Direct-fetch providers: %s",
            provider, ", ".join(sorted(SECRET_ENV_BY_PROVIDER)),
        )
        sys.exit(1)

    try:
        token = getpass.getpass(f"Paste the {provider} token (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not token:
        log.error("No token entered — nothing written.")
        sys.exit(1)

    path = write_secret(env_var, token)
    print(f"Saved {env_var} to {path} (mode 0600).")


def _poll(provider_names: list[str], config) -> list[dict[str, object]]:
    """Shared logic: poll providers, return results list.

    Providers that implement :class:`DirectFetchProvider` (currently Kimi
    and MiniMax) are polled via their direct API path. The browser is
    launched only when at least one provider needs it (browser-only
    providers, or failed direct providers when
    ``config.direct_fetch_browser_fallback`` is True). This lets pure
    direct-API runs complete without ever instantiating Playwright.
    """
    from poller.providers import get_enabled_providers
    from poller.providers.base import BaseProvider, UsageData
    from poller.providers.direct import DirectFetchProvider

    resolved_timezone = config.timezone or get_system_timezone()
    providers = get_enabled_providers(provider_names, timezone_id=resolved_timezone)

    if not providers:
        log.warning("No providers enabled.")
        return []

    results_by_index: dict[int, dict[str, object]] = {}
    browser_queue: list[tuple[int, BaseProvider]] = []

    for index, provider in enumerate(providers):
        is_direct_capable = (
            isinstance(provider, DirectFetchProvider) and provider.supports_direct_fetch
        )
        # Per-provider opt-in gate. Claude defaults to browser scraping;
        # Kimi/MiniMax default to direct. The widget surfaces these as a
        # "fetch method" choice and writes the matching *_use_direct_fetch flag.
        direct_flag = _DIRECT_FETCH_FLAGS.get(provider.name)
        if direct_flag is not None and not getattr(config, direct_flag):
            is_direct_capable = False
        if not is_direct_capable:
            browser_queue.append((index, provider))
            continue

        direct_provider = cast(DirectFetchProvider, provider)
        log.info("Polling %s (direct API) ...", provider.name)
        try:
            data = direct_provider.fetch_direct(config)
        except Exception as exc:
            log.error("%s ✗  %s", provider.name, exc)
            data = UsageData(
                provider=provider.name,
                window_5h_percent=0.0,
                window_7d_percent=0.0,
                error=str(exc),
            )

        if data.error:
            log.error("%s ✗  %s", provider.name, data.error)
            if config.direct_fetch_browser_fallback:
                browser_queue.append((index, provider))
            else:
                results_by_index[index] = data.model_dump(mode="json")
        else:
            results_by_index[index] = data.model_dump(mode="json")
            log.info(
                "%s ✓  5h=%.0f%%  7d=%.0f%%",
                provider.name,
                data.window_5h_percent,
                data.window_7d_percent,
            )
        time.sleep(1)

    if not browser_queue:
        return [results_by_index[index] for index in range(len(providers))]

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    if not browser_dir.exists():
        log.error("No browser profile found at %s. Run --login first.", browser_dir)
        sys.exit(1)

    with ManagedBrowser(headless=True, data_dir=browser_dir, timezone=resolved_timezone) as browser:
        context = browser.get_context()
        for index, provider in browser_queue:
            log.info("Polling %s ...", provider.name)
            try:
                data = provider.fetch(context)
                results_by_index[index] = data.model_dump(mode="json")
                log.info(
                    "%s ✓  5h=%.0f%%  7d=%.0f%%",
                    provider.name,
                    data.window_5h_percent,
                    data.window_7d_percent,
                )
            except Exception as exc:
                results_by_index[index] = {
                    "provider": provider.name,
                    "error": str(exc),
                    "window_5h_percent": None,
                    "window_7d_percent": None,
                }
                log.error("%s ✗  %s", provider.name, exc)
            # Small delay between providers to let Playwright fully clean up pages
            time.sleep(1)
    return [results_by_index[index] for index in range(len(providers))]


def _handle_oneshot(provider_names: list[str], config) -> None:
    """Run a single poll cycle and write results to disk."""
    results = _poll(provider_names, config)
    if results:
        save_results(results, data_dir=config.data_dir)
        log.info("Results written to storage (%d providers).", len(results))
    else:
        log.warning("Nothing to save.")


def _handle_debug_dump(provider_names: list[str], config) -> None:
    """Open each provider's dashboard in a headed browser and dump the page content."""
    log.info("=== DEBUG MODE: dumping page content ===")

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    if not browser_dir.exists():
        log.error("No browser profile found at %s. Run --login first.", browser_dir)
        sys.exit(1)

    PROVIDER_URLS: dict[str, str] = {
        "codex":   "https://chatgpt.com/codex/cloud/settings/analytics",
        "claude":  "https://claude.ai/new#settings/usage",
        "kimi":    "https://www.kimi.com/code/console",
        "minimax": "https://platform.minimaxi.com/console/usage",
    }

    from poller.providers import get_enabled_providers

    resolved_timezone = config.timezone or get_system_timezone()
    providers = get_enabled_providers(provider_names, timezone_id=resolved_timezone)
    dump_dir = Path("/tmp/show-ai-usage-debug")
    dump_dir.mkdir(parents=True, exist_ok=True)

    with ManagedBrowser(headless=False, data_dir=browser_dir, timezone=resolved_timezone) as browser:
        context = browser.get_context()

        for provider in providers:
            url = PROVIDER_URLS.get(provider.name)
            if not url:
                log.warning("No debug URL configured for %s", provider.name)
                continue

            log.info("--- %s -> %s ---", provider.name, url)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                log.info("Waiting for page to render (up to 45s)...")
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
                log.info("Saved: %s/%s.{html,txt,png}", dump_dir, provider.name)
                log.info("Page title: %s", page.title())
                log.info("Body text length: %d chars", len(text))

                if text.strip():
                    try:
                        data = provider.fetch(context)
                        log.info("Parse result: %s", data.model_dump_json())
                    except Exception as exc:
                        log.error("Parse failed: %s", exc)
                else:
                    log.warning("Body empty — page likely still loading or blocked.")
            except Exception as e:
                log.error("Error dumping %s: %s", provider.name, e)
            finally:
                page.close()


def _handle_daemon(provider_names: list[str], config) -> None:
    """Run in a loop, polling providers every *config.interval* seconds."""
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    browser_dir = _get_browser_data_dir(config.browser_data_dir)
    if not browser_dir.exists():
        log.error("No browser profile found at %s. Run --login first.", browser_dir)
        sys.exit(1)

    interval = config.interval

    log.info("Daemon started — polling %d provider(s) every %ds", len(provider_names), interval)
    log.info("Config: %s", CONFIG_FILE)
    log.info("Press Ctrl+C to stop.")

    while _running:
        cycle_start = time.time()
        log.info("[%s] Polling ...", datetime.now().strftime("%H:%M:%S"))
        results = _poll(provider_names, config)
        if results:
            save_results(results, data_dir=config.data_dir)
        elapsed = time.time() - cycle_start
        sleep = max(0, interval - elapsed)
        if _running and sleep > 0:
            time.sleep(sleep)
        log.info("Cycle completed (%.0fs)", elapsed)

    log.info("Daemon stopped.")


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
        reset_5h = prov.get("reset_5h")
        reset_7d = prov.get("reset_7d")

        print(f"  {name}")
        print(f"    5h: {p5:.0f}%" if p5 is not None else "    5h: N/A")
        print(f"    7d: {p7:.0f}%" if p7 is not None else "    7d: N/A")
        if reset_5h:
            print(f"    重置(5h): {reset_5h}")
        if reset_7d:
            print(f"    重置(7d): {reset_7d}")
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
        "--set-token",
        type=str,
        default=None,
        metavar="PROVIDER",
        help="Securely store a direct-API credential in secrets.env (0600). "
             "Providers: kimi, minimax, claude.",
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

    if args.set_token:
        setup_logging("INFO")
        _handle_set_token(args.set_token)
        return

    # ── Load config & merge CLI overrides ─────────────────────────
    cfg = load_config()
    cfg = merge_cli_overrides(
        cfg,
        interval=args.interval,
        providers=args.providers,
    )

    # Initialise logging based on config
    level = "DEBUG" if args.debug else cfg.log_level
    setup_logging(level)

    log.debug("Configuration loaded: %s", cfg.redacted_json(indent=2))

    if args.show_config:
        # Always mask credential fields — secrets must not be printed
        # to stdout even when --show-config is invoked with env vars set.
        print(cfg.redacted_json(indent=2))
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
