"""Multi-channel LLM job scheduler.

Manages four bounded channels with priority, concurrency limits,
per-channel cooldowns, and stale-job collapse.

Usage:
    scheduler = LLMScheduler(client)
    scheduler.submit("council", prompt, priority=10, stale_key="council_v42")
    completed = scheduler.poll()
    for job in completed:
        print(job.channel, job.response_text or job.error)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from llm import ALL_CHANNELS
from llm.client import OllamaClient, get_channel_options

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

@dataclass
class LLMJob:
    channel: str
    prompt: str
    priority: int
    stale_key: str
    snapshot_version: int = 0
    queued_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    response_text: str | None = None
    model_used: str | None = None
    error: Exception | None = None
    done: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def is_done(self) -> bool:
        return self.done.is_set()

    @property
    def succeeded(self) -> bool:
        return self.is_done and self.error is None and self.response_text is not None


# ---------------------------------------------------------------------------
# Channel status
# ---------------------------------------------------------------------------

@dataclass
class ChannelStatus:
    channel: str
    active: bool = False
    queued: int = 0
    last_success_at: float = 0.0
    last_error_at: float = 0.0
    last_error_msg: str = ""
    total_requests: int = 0
    total_errors: int = 0
    total_successes: int = 0
    cooldown_until: float = 0.0

    @property
    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

# Default per-channel cooldown after failure (seconds)
_DEFAULT_BACKOFF = 45.0
# Maximum concurrent Ollama requests across all channels
_MAX_CONCURRENT = 2


class LLMScheduler:
    """Manages async LLM requests across four named channels."""

    def __init__(
        self,
        client: OllamaClient,
        max_concurrent: int = _MAX_CONCURRENT,
        default_backoff: float = _DEFAULT_BACKOFF,
    ):
        self._client = client
        self._max_concurrent = max_concurrent
        self._default_backoff = default_backoff

        self._lock = threading.Lock()

        # Per-channel pending queue (at most 1 queued job per channel)
        self._queued: dict[str, LLMJob] = {}
        # Currently running jobs (at most 1 per channel)
        self._active: dict[str, LLMJob] = {}
        # Completed jobs waiting to be polled
        self._completed: list[LLMJob] = []
        # Per-channel status tracking
        self._status: dict[str, ChannelStatus] = {
            ch: ChannelStatus(channel=ch) for ch in ALL_CHANNELS
        }

    # ---- public API -------------------------------------------------------

    def submit(
        self,
        channel: str,
        prompt: str,
        priority: int = 5,
        stale_key: str = "",
        snapshot_version: int = 0,
    ) -> bool:
        """Enqueue a job for *channel*.

        If an existing queued job shares the same *stale_key* it is replaced
        (stale-collapse).  Returns True if the job was accepted.
        """
        if channel not in ALL_CHANNELS:
            logger.warning("[Scheduler] Unknown channel: %s", channel)
            return False

        if not self._client.available:
            return False

        with self._lock:
            status = self._status[channel]

            # Respect cooldown
            if status.in_cooldown:
                return False

            # Already running on this channel?  Queue it (replacing stale).
            job = LLMJob(
                channel=channel,
                prompt=prompt,
                priority=priority,
                stale_key=stale_key or f"{channel}_{time.monotonic()}",
                snapshot_version=snapshot_version,
            )

            if channel in self._active:
                # Stale-collapse: replace any existing queued job for this channel
                old = self._queued.get(channel)
                if old:
                    logger.debug(
                        "[Scheduler] Stale collapse on %s (key %s → %s)",
                        channel,
                        old.stale_key,
                        job.stale_key,
                    )
                self._queued[channel] = job
                status.queued = 1
                return True

            # Try to start immediately
            if self._running_count() < self._max_concurrent:
                self._start_job(job)
                return True

            # Cannot start now — queue
            self._queued[channel] = job
            status.queued = 1
            return True

    def poll(self) -> list[LLMJob]:
        """Return completed jobs and try to start queued work."""
        with self._lock:
            # Collect completions
            completed = list(self._completed)
            self._completed.clear()

            # Move completed active jobs
            finished_channels: list[str] = []
            for ch, job in list(self._active.items()):
                if job.is_done:
                    finished_channels.append(ch)
                    completed.append(job)
                    self._record_completion(job)

            for ch in finished_channels:
                del self._active[ch]

            # Try to promote queued jobs
            self._promote_queued()

        return completed

    def get_channel_status(self, channel: str) -> ChannelStatus:
        with self._lock:
            return self._status.get(channel, ChannelStatus(channel=channel))

    def get_stats(self) -> dict[str, Any]:
        """Aggregate stats for archiving."""
        with self._lock:
            return {
                ch: {
                    "total_requests": s.total_requests,
                    "total_successes": s.total_successes,
                    "total_errors": s.total_errors,
                    "last_error_msg": s.last_error_msg,
                    "in_cooldown": s.in_cooldown,
                }
                for ch, s in self._status.items()
            }

    def has_active_jobs(self) -> bool:
        with self._lock:
            return bool(self._active)

    def get_active_channels(self) -> list[str]:
        with self._lock:
            return list(self._active.keys())

    # ---- internals --------------------------------------------------------

    def _running_count(self) -> int:
        return len(self._active)

    def _start_job(self, job: LLMJob) -> None:
        """Start a job on a background thread.  Caller must hold _lock."""
        job.started_at = time.time()
        self._active[job.channel] = job
        self._status[job.channel].active = True
        self._status[job.channel].queued = 0
        self._status[job.channel].total_requests += 1

        def _run() -> None:
            try:
                options = get_channel_options(job.channel, self._client.seed)
                text, model = self._client.generate(
                    job.prompt, channel=job.channel, options=options
                )
                job.response_text = text
                job.model_used = model
            except Exception as exc:
                job.error = exc
            finally:
                job.completed_at = time.time()
                job.done.set()

        t = threading.Thread(
            target=_run, daemon=True, name=f"llm-{job.channel}"
        )
        job._thread = t
        t.start()

        logger.debug(
            "[Scheduler] Started %s job (priority=%d, stale_key=%s)",
            job.channel,
            job.priority,
            job.stale_key,
        )

    def _record_completion(self, job: LLMJob) -> None:
        """Update channel status after job completion.  Caller holds _lock."""
        status = self._status[job.channel]
        status.active = False
        if job.error is not None:
            status.total_errors += 1
            status.last_error_at = job.completed_at
            status.last_error_msg = str(job.error)[:200]
            status.cooldown_until = time.time() + self._default_backoff
            logger.warning(
                "[Scheduler] %s failed: %s (cooldown %.0fs)",
                job.channel,
                job.error,
                self._default_backoff,
            )
        else:
            status.total_successes += 1
            status.last_success_at = job.completed_at
            status.cooldown_until = 0.0

    def _promote_queued(self) -> None:
        """Start queued jobs if concurrency slots are free.  Caller holds _lock."""
        if not self._queued:
            return

        # Sort queued by priority (highest first)
        pending = sorted(
            self._queued.values(), key=lambda j: j.priority, reverse=True
        )

        for job in pending:
            if self._running_count() >= self._max_concurrent:
                break
            if job.channel in self._active:
                continue  # channel already running
            if self._status[job.channel].in_cooldown:
                continue
            del self._queued[job.channel]
            self._status[job.channel].queued = 0
            self._start_job(job)
