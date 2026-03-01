"""
src/alerts.py — Multi-channel alert dispatcher.

Channels:
  ConsoleChannel — coloured stdout
  FileChannel    — JSONL log at logs/alerts.log
  SlackChannel   — stub (set SLACK_WEBHOOK_URL to enable)

Add new channels by subclassing BaseChannel and implementing send().
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from .signals import Signal

logger = logging.getLogger(__name__)
ALERT_LOG_PATH = Path(__file__).parent.parent / "logs" / "alerts.log"


class BaseChannel(ABC):
    @abstractmethod
    def send(self, signal: Signal): ...


class ConsoleChannel(BaseChannel):
    ICONS = {
        "PRICE_SPIKE":      "🔺",
        "VOLUME_SURGE":     "📊",
        "VOLATILITY_BURST": "⚡",
        "VWAP_DEVIATION":   "📌",
    }
    def send(self, signal: Signal):
        icon = self.ICONS.get(signal.signal_type, "🚨")
        ts   = signal.timestamp.strftime("%H:%M:%S")
        print(f"\n  {icon}  ALERT [{ts}] {signal}")


class FileChannel(BaseChannel):
    def __init__(self, path: Path = ALERT_LOG_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, signal: Signal):
        record = {
            "ts":       signal.timestamp.isoformat(),
            "type":     signal.signal_type,
            "symbol":   signal.symbol,
            "price":    signal.price,
            "message":  signal.message,
            "metadata": signal.metadata,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")


class SlackChannel(BaseChannel):
    """Uncomment requests lines and set SLACK_WEBHOOK_URL to activate."""
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, signal: Signal):
        # import requests
        # requests.post(self.webhook_url, json={
        #     "text": f"*{signal.signal_type}* `{signal.symbol}` — {signal.message}"
        # })
        logger.info(f"[SlackChannel stub] {signal}")


class AlertManager:
    def __init__(self, channels: list[BaseChannel] | None = None):
        self.channels = channels or [ConsoleChannel(), FileChannel()]

    def fire(self, signal: Signal):
        logger.info(f"Signal: {signal}")
        for ch in self.channels:
            try:
                ch.send(signal)
            except Exception as e:
                logger.error(f"{ch.__class__.__name__} failed: {e}")
