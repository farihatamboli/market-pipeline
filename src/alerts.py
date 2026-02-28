"""
alerts.py — Dispatches fired signals to configured output channels.

Channels implemented:
  - Console (always on)
  - File log (written to logs/alerts.log)
  - Extendable: add Slack, email, or webhook by subclassing BaseChannel
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from .signals import Signal

logger = logging.getLogger(__name__)

ALERT_LOG_PATH = Path(__file__).parent.parent / "logs" / "alerts.log"


class BaseChannel(ABC):
    """Abstract alert output channel. Implement `send` to add a new destination."""

    @abstractmethod
    def send(self, signal: Signal):
        pass


class ConsoleChannel(BaseChannel):
    """Prints alerts to stdout with clear formatting."""

    ICONS = {
        "PRICE_SPIKE": "🔺",
        "VOLUME_SURGE": "📊",
        "VOLATILITY_BURST": "⚡",
        "VWAP_DEVIATION": "📌",
    }

    def send(self, signal: Signal):
        icon = self.ICONS.get(signal.signal_type, "🚨")
        ts = signal.timestamp.strftime("%H:%M:%S")
        print(f"\n  {icon}  ALERT [{ts}] {signal}")


class FileChannel(BaseChannel):
    """Appends JSON alert records to a log file."""

    def __init__(self, path: Path = ALERT_LOG_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, signal: Signal):
        record = {
            "ts": signal.timestamp.isoformat(),
            "type": signal.signal_type,
            "symbol": signal.symbol,
            "price": signal.price,
            "message": signal.message,
            "metadata": signal.metadata,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")


class SlackChannel(BaseChannel):
    """
    Stub for Slack webhook alerts. Set SLACK_WEBHOOK_URL env var to enable.
    Uncomment and install `requests` to use in production.
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, signal: Signal):
        # import requests
        # payload = {"text": f"*{signal.signal_type}* {signal.symbol}: {signal.message}"}
        # requests.post(self.webhook_url, json=payload)
        logger.info(f"[SlackChannel stub] Would send: {signal}")


class AlertManager:
    """Routes signals to all registered output channels."""

    def __init__(self, channels: list[BaseChannel] | None = None):
        self.channels = channels or [
            ConsoleChannel(),
            FileChannel(),
        ]

    def fire(self, signal: Signal):
        logger.info(f"Firing signal: {signal}")
        for channel in self.channels:
            try:
                channel.send(signal)
            except Exception as e:
                logger.error(f"Alert channel {channel.__class__.__name__} failed: {e}")
