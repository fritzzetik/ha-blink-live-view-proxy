"""Whether this proxy can replace its own code, and starting it when it can.

The proxy gets installed three ways and only one of them can update itself. A
systemd host install ships an updater unit that reruns bootstrap.sh; the add-on
belongs to Supervisor; a container cannot rewrite the image it is running from.

So most of this module's work is saying *no* accurately. The integration puts a
Fix button in front of the user based on what it reads here, and a button that
cannot work is worse than no button at all.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import LOGGER_NAME

LOGGER = logging.getLogger(LOGGER_NAME)

# Both are put there by scripts/install-proxy.sh. The unit is a separate
# one-shot rather than something this process runs itself - see start().
UPDATE_UNIT = "blink-liveview-proxy-update.service"
UPDATE_SCRIPT = Path("/usr/local/sbin/blink-liveview-proxy-update.sh")
UPDATE_UNIT_FILE = Path("/etc/systemd/system") / UPDATE_UNIT
# install-proxy.sh writes SRC_DIR here and the unit reads it through
# EnvironmentFile=, so this is where to look for the checkout the updater moves
# between tags.
UPDATE_ENV_FILE = Path("/etc/blink-liveview-proxy/update.env")
DEFAULT_SRC_DIR = Path("/opt/src/ha-blink-live-view-proxy")
# Docker writes this into every container it starts, and nothing else does.
DOCKER_MARKER = Path("/.dockerenv")

METHOD_SUPERVISOR = "supervisor"
METHOD_SYSTEMD = "systemd"
METHOD_CONTAINER = "container"
METHOD_MANUAL = "manual"

# Said to a person, in the integration's repair notice, so each one names the
# thing to go and do instead.
REASONS = {
    METHOD_SUPERVISOR: "Supervisor updates this add-on from the add-on store.",
    METHOD_CONTAINER: (
        "A container cannot replace its own image. Pull the new tag and "
        "recreate the container."
    ),
    METHOD_MANUAL: (
        "This install has no updater unit. Re-run scripts/install-proxy.sh on "
        "the proxy host to add one."
    ),
}


class UpdateUnavailableError(RuntimeError):
    """This install has no way to update itself."""


class UpdateBusyError(RuntimeError):
    """An update is already running."""


@lru_cache(maxsize=1)
def detect_method() -> str:
    """Name how this install gets new code.

    Cached for the life of the process, which is also exactly as long as the
    answer can change: installing the updater unit means running
    install-proxy.sh, and that restarts this service. Without the cache every
    /status poll would stat three paths on the event loop.
    """
    # Supervisor first. The add-on is a container too, and "Supervisor owns
    # this" is the more useful of the two true answers.
    if os.getenv("SUPERVISOR_TOKEN"):
        return METHOD_SUPERVISOR
    if (
        UPDATE_UNIT_FILE.exists()
        and UPDATE_SCRIPT.exists()
        and shutil.which("systemctl")
    ):
        return METHOD_SYSTEMD
    if DOCKER_MARKER.exists():
        return METHOD_CONTAINER
    return METHOD_MANUAL


def describe() -> dict[str, Any]:
    """What /status tells the integration about updating this install."""
    method = detect_method()
    supported = method == METHOD_SYSTEMD
    described: dict[str, Any] = {"method": method, "supported": supported}
    if not supported:
        described["reason"] = REASONS[method]
    return described


async def _systemctl(*args: str) -> int:
    process = await asyncio.create_subprocess_exec(
        "systemctl",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await process.wait()


async def is_running() -> bool:
    """Whether the updater unit is mid-run."""
    return await _systemctl("is-active", "--quiet", UPDATE_UNIT) == 0


def source_dir() -> Path:
    """Where the checkout the updater moves between tags lives."""
    override = os.getenv("SRC_DIR")
    if override:
        return Path(override)
    try:
        for line in UPDATE_ENV_FILE.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "SRC_DIR" and value.strip():
                return Path(value.strip())
    except OSError:
        pass
    return DEFAULT_SRC_DIR


async def _run(*args: str) -> tuple[int, str]:
    """Run a command, returning its exit code and combined output."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    return process.returncode or 0, output.decode("utf-8", "replace")


async def preflight() -> list[str]:
    """Repair the one thing that silently stops every future update.

    A tag that was recreated upstream - a prerelease deleted, a release re-cut -
    points somewhere else than the copy already on this host, and a plain
    `git fetch --tags` refuses to move it. It exits 1 saying "would clobber
    existing tag", except that bootstrap.sh passes --quiet, which suppresses
    exactly that line. Under its `set -e` the script then dies in under a
    second having printed nothing at all, the host stays on its old version,
    and every later press of the button in Home Assistant fails the same silent
    way. One host sat wedged from the 0.7.0 prereleases until 0.8.0.

    bootstrap.sh now fetches with --force, which fixes it going forward - but a
    wedged host can never install the version that carries the fix, because
    installing it is the thing that is broken. So the repair has to happen from
    this side, before the unit starts. Cheap: on a healthy host it is one fetch
    that exits 0 and reports nothing.
    """
    notes: list[str] = []
    src = source_dir()
    if not (src / ".git").is_dir():
        return notes
    if not shutil.which("git"):
        return notes

    code, _ = await _run("git", "-C", str(src), "fetch", "--tags", "--prune", "--quiet")
    if code == 0:
        return notes

    # Find out what a plain fetch would have said, now that --quiet is not
    # hiding it, so the reason reaches the log either way.
    _, detail = await _run("git", "-C", str(src), "fetch", "--tags", "--prune")
    rejected = [
        line.strip()
        for line in detail.splitlines()
        if "rejected" in line or "clobber" in line
    ]
    forced, output = await _run(
        "git", "-C", str(src), "fetch", "--tags", "--prune", "--force"
    )
    if forced == 0:
        moved = [line.strip() for line in output.splitlines() if "tag update" in line]
        note = (
            f"Tag fetch in {src} exited {code} and was repaired with --force"
            + (f": {', '.join(moved)}" if moved else ".")
        )
        notes.append(note)
        LOGGER.warning(
            "Repaired a wedged update checkout in %s: a plain tag fetch exited "
            "%s%s. Forced fetch succeeded%s",
            src,
            code,
            f" ({'; '.join(rejected)})" if rejected else "",
            f", moving {len(moved)} tag(s)" if moved else "",
        )
    else:
        note = f"Tag fetch in {src} failed ({code}), and --force did not fix it."
        notes.append(note)
        LOGGER.error(
            "Update checkout in %s cannot fetch tags: plain fetch exited %s, "
            "forced fetch exited %s. Output: %s",
            src,
            code,
            forced,
            output.strip()[:500],
        )
    return notes


async def recent_log(lines: int = 200) -> dict[str, Any]:
    """The updater unit's own journal, for showing next to the button.

    The panel used to tell people to "check the log" without saying which log
    or giving them a way to see it, which on a headless box means finding an
    SSH session before you can learn anything at all.
    """
    if detect_method() != METHOD_SYSTEMD:
        raise UpdateUnavailableError(REASONS[detect_method()])
    if not shutil.which("journalctl"):
        return {
            "unit": UPDATE_UNIT,
            "available": False,
            "reason": "journalctl is not available on this host.",
            "lines": [],
        }
    capped = max(1, min(int(lines), 1000))
    code, output = await _run(
        "journalctl",
        "-u",
        UPDATE_UNIT,
        "-n",
        str(capped),
        "--no-pager",
    )
    if code != 0:
        return {
            "unit": UPDATE_UNIT,
            "available": False,
            "reason": f"journalctl exited {code}.",
            "lines": [],
        }
    _, state = await _run("systemctl", "show", UPDATE_UNIT, "-p", "Result", "--value")
    return {
        "unit": UPDATE_UNIT,
        "available": True,
        "result": state.strip() or None,
        "lines": output.splitlines(),
    }


async def start() -> dict[str, Any]:
    """Start the installed updater unit. Takes no arguments, deliberately.

    Nothing about what gets installed comes from the caller: no tag, no ref, no
    repository URL. The unit, and the script it runs, were fixed at install
    time. An endpoint that accepted a version to install would be a way to run
    chosen code as root on the camera host wearing the clothes of an update
    button, so there is no parameter here to add one to.

    `--no-block`, on a unit of its own, is the other load-bearing detail.
    bootstrap.sh restarts blink-liveview-proxy.service, and systemd stops a
    service by killing its whole cgroup: an updater running as a child of this
    process would kill itself halfway through the upgrade it was performing.
    Started this way it belongs to its own unit and survives the restart it
    causes.
    """
    method = detect_method()
    if method != METHOD_SYSTEMD:
        raise UpdateUnavailableError(REASONS[method])
    if await is_running():
        raise UpdateBusyError("An update is already running.")

    # Before the unit, not inside it: a host wedged this way cannot install the
    # bootstrap.sh that fixes it, so the repair has to come from outside.
    notes = await preflight()

    code = await _systemctl("start", "--no-block", UPDATE_UNIT)
    if code != 0:
        raise UpdateUnavailableError(
            f"systemctl start {UPDATE_UNIT} exited {code}. "
            f"Check: journalctl -u {UPDATE_UNIT}"
        )

    LOGGER.info("Started %s at the integration's request", UPDATE_UNIT)
    # "Started", not "updated": the unit exits early when the newest tag is
    # already installed, and the integration confirms by watching the version
    # on /status change, not by believing this.
    started: dict[str, Any] = {
        "started": True,
        "method": METHOD_SYSTEMD,
        "unit": UPDATE_UNIT,
    }
    if notes:
        started["preflight"] = notes
    return started
