"""
src/webhooks.py — Discord and Slack webhook alert channels.

Both implement BaseChannel so they plug directly into AlertManager.

Setup:
    Discord: Server Settings → Integrations → Webhooks → Copy URL
    Slack:   api.slack.com/apps → Incoming Webhooks → Activate → Copy URL

Usage:
    import os
    from src.webhooks import DiscordChannel, SlackChannel
    from src.alerts import AlertManager

    alerts = AlertManager(channels=[
        DiscordChannel(os.environ["DISCORD_WEBHOOK_URL"]),
        SlackChannel(os.environ["SLACK_WEBHOOK_URL"]),
    ])

Environment variables:
    DISCORD_WEBHOOK_URL  — Discord webhook endpoint
    SLACK_WEBHOOK_URL    — Slack webhook endpoint
    WEBHOOK_MIN_INTERVAL — Minimum seconds between alerts (default: 30)
                           Prevents webhook rate-limit bans during volatile periods
"""

import os
import json
import time
import logging
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime

from .alerts import BaseChannel
from .signals import Signal, SignalType

logger = logging.getLogger(__name__)

# Rate limit: don't fire more than 1 alert per symbol per N seconds
_DEFAULT_COOLDOWN = int(os.environ.get("WEBHOOK_MIN_INTERVAL", 30))

# Emoji map
_EMOJI = {
    SignalType.PRICE_SPIKE:       "🔺",
    SignalType.VOLUME_SURGE:      "📊",
    SignalType.VOLATILITY_BURST:  "⚡",
    SignalType.VWAP_DEVIATION:    "📌",
}

# Color map (Discord embed colors)
_COLORS = {
    SignalType.PRICE_SPIKE:       0xFF4060,
    SignalType.VOLUME_SURGE:      0x38BDF8,
    SignalType.VOLATILITY_BURST:  0xF5A623,
    SignalType.VWAP_DEVIATION:    0x00E5A0,
}


def _post(url: str, payload: dict):
    """Simple HTTP POST using stdlib — no requests dependency."""
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        logger.error(f"Webhook HTTP error {e.code}: {e.reason}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")


class _RateLimiter:
    """Per-symbol cooldown to prevent alert floods."""
    def __init__(self, cooldown: int = _DEFAULT_COOLDOWN):
        self._last: dict[str, float] = defaultdict(float)
        self.cooldown = cooldown

    def allow(self, key: str) -> bool:
        now = time.time()
        if now - self._last[key] >= self.cooldown:
            self._last[key] = now
            return True
        return False


class DiscordChannel(BaseChannel):
    """
    Posts signal alerts to a Discord channel via webhook.

    Features rich embeds with:
      - Color-coded by signal type
      - Price, timestamp, signal metadata fields
      - Footer with pipeline attribution

    Args:
        webhook_url: Discord webhook URL
        cooldown:    Min seconds between alerts per symbol (default 30)
        min_types:   Only fire for these signal types (None = all)
    """

    def __init__(
        self,
        webhook_url: str = "",
        cooldown:    int  = _DEFAULT_COOLDOWN,
        min_types:   list | None = None,
    ):
        self.url       = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
        self._rl       = _RateLimiter(cooldown)
        self.min_types = set(min_types) if min_types else None

        if not self.url:
            logger.warning("DiscordChannel: no webhook URL set — alerts will be skipped.")

    def send(self, signal: Signal):
        if not self.url:
            return
        if self.min_types and signal.signal_type not in self.min_types:
            return
        if not self._rl.allow(f"{signal.symbol}:{signal.signal_type}"):
            logger.debug(f"Discord rate-limited: {signal.symbol}")
            return

        emoji = _EMOJI.get(signal.signal_type, "🚨")
        color = _COLORS.get(signal.signal_type, 0xFFFFFF)
        ts    = signal.timestamp.strftime("%H:%M:%S UTC")

        fields = [
            {"name": "Symbol",  "value": f"`{signal.symbol}`",        "inline": True},
            {"name": "Price",   "value": f"`${signal.price:.2f}`",     "inline": True},
            {"name": "Time",    "value": f"`{ts}`",                    "inline": True},
        ]
        for k, v in signal.metadata.items():
            fields.append({"name": k.replace("_", " ").title(), "value": f"`{v}`", "inline": True})

        payload = {
            "embeds": [{
                "title":       f"{emoji} {signal.signal_type.replace('_', ' ')}",
                "description": signal.message,
                "color":       color,
                "fields":      fields,
                "footer":      {"text": "Market Data Pipeline"},
                "timestamp":   signal.timestamp.isoformat(),
            }]
        }
        status = _post(self.url, payload)
        if status and status < 300:
            logger.info(f"Discord alert sent: {signal.symbol} {signal.signal_type}")


class SlackChannel(BaseChannel):
    """
    Posts signal alerts to a Slack channel via incoming webhook.

    Uses Block Kit for rich formatting.

    Args:
        webhook_url: Slack webhook URL
        cooldown:    Min seconds between alerts per symbol (default 30)
    """

    def __init__(
        self,
        webhook_url: str = "",
        cooldown:    int  = _DEFAULT_COOLDOWN,
    ):
        self.url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
        self._rl = _RateLimiter(cooldown)

        if not self.url:
            logger.warning("SlackChannel: no webhook URL set — alerts will be skipped.")

    def send(self, signal: Signal):
        if not self.url:
            return
        if not self._rl.allow(f"{signal.symbol}:{signal.signal_type}"):
            logger.debug(f"Slack rate-limited: {signal.symbol}")
            return

        emoji = _EMOJI.get(signal.signal_type, "🚨")
        ts    = signal.timestamp.strftime("%H:%M:%S UTC")
        meta  = "  •  ".join(f"{k}: `{v}`" for k, v in signal.metadata.items())

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{emoji} {signal.signal_type.replace('_', ' ')}"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Symbol*\n`{signal.symbol}`"},
                        {"type": "mrkdwn", "text": f"*Price*\n`${signal.price:.2f}`"},
                        {"type": "mrkdwn", "text": f"*Time*\n`{ts}`"},
                        {"type": "mrkdwn", "text": f"*Message*\n{signal.message}"},
                    ]
                },
            ]
        }
        if meta:
            payload["blocks"].append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": meta}]
            })

        status = _post(self.url, payload)
        if status and status < 300:
            logger.info(f"Slack alert sent: {signal.symbol} {signal.signal_type}")


class WebhookManager:
    """
    Convenience wrapper — reads URLs from environment and builds
    the right channels automatically.

    Usage:
        from src.webhooks import WebhookManager
        from src.alerts import AlertManager, ConsoleChannel

        alerts = AlertManager(channels=[
            ConsoleChannel(),
            *WebhookManager.from_env(),
        ])
    """

    @staticmethod
    def from_env() -> list[BaseChannel]:
        channels = []
        if os.environ.get("DISCORD_WEBHOOK_URL"):
            channels.append(DiscordChannel())
            logger.info("Discord webhook enabled.")
        if os.environ.get("SLACK_WEBHOOK_URL"):
            channels.append(SlackChannel())
            logger.info("Slack webhook enabled.")
        if not channels:
            logger.info("No webhook URLs set. Set DISCORD_WEBHOOK_URL or SLACK_WEBHOOK_URL to enable.")
        return channels
