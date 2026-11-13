"""
Desktop notifications

A Windows toast through Windows PowerShell's WinRT bindings, so nothing extra
needs installing. Toasts only show in a logged-on session: a scheduled task
has to run "only when the user is logged on". Elsewhere this is a no-op.
"""

import base64
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Toasts need a registered app ID; PowerShell's own is always there
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# The text comes in through environment variables, so nothing needs quoting
_SCRIPT = r"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
function Esc($s) { [System.Security.SecurityElement]::Escape($s) }
$launch = ''
if ($env:QUANT_TOAST_LAUNCH) { $launch = ' activationType="protocol" launch="' + (Esc $env:QUANT_TOAST_LAUNCH) + '"' }
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast' + $launch + '><visual><binding template="ToastGeneric"><text>' + (Esc $env:QUANT_TOAST_TITLE) + '</text><text>' + (Esc $env:QUANT_TOAST_TEXT) + '</text></binding></visual></toast>')
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:QUANT_TOAST_APP).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def toast(title: str, message: str, open_path: Path | None = None) -> bool:
    """
    Show a desktop notification; clicking it opens `open_path`, if given.
    Returns whether it was sent. Never raises: a missed notification
    shouldn't fail the run that wanted it.
    """
    if sys.platform != "win32":
        logger.info("Notifications are only supported on Windows")
        return False
    env = {
        **os.environ,
        "QUANT_TOAST_TITLE": title,
        "QUANT_TOAST_TEXT": message,
        "QUANT_TOAST_LAUNCH": open_path.resolve().as_uri() if open_path else "",
        "QUANT_TOAST_APP": _APP_ID,
    }
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Notification failed: {e}")
        return False
    if result.returncode != 0:
        logger.warning(f"Notification failed: {result.stderr.strip()[:300]}")
        return False
    return True
