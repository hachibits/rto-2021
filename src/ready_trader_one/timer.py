import asyncio
import logging
import time

from typing import Any, Callable, List, Optional

from .market_events import MarketEventsReader


class Timer:
    """A timer."""

    def __init__(self, loop: asyncio.AbstractEventLoop, tick_interval: float, speed: float,
                 market_events_reader: MarketEventsReader):
        """Initialise a new instance of the timer class."""
        self.__event_loop: asyncio.AbstractEventLoop = loop
        self.__logger: logging.Logger = logging.getLogger("TIMER")
        self.__market_events_reader: MarketEventsReader = market_events_reader
        self.__speed: float = speed
        self.__start_time: float = 0.0
        self.__tick_timer_handle: Optional[asyncio.TimerHandle] = None
        self.__tick_interval: float = tick_interval

        # Signals
        self.timer_started: List[Callable[[Any, float], None]] = list()
        self.timer_stopped: List[Callable[[Any, float], None]] = list()
        self.timer_ticked: List[Callable[[Any, float, int], None]] = list()

    def advance(self) -> float:
        """Advance the timer."""
        if self.__start_time:
            now = (time.monotonic() - self.__start_time) * self.__speed
            self.__market_events_reader.process_market_events(now)
            return now
        return 0.0

    def __on_timer_tick(self, tick_time: float, tick_number: int):
        """Called on each timer tick."""
        now = (time.monotonic() - self.__start_time) * self.__speed
        self.__market_events_reader.process_market_events(now)

        # There may have been a delay, so work out which tick this really is
        skipped_ticks: float = (now - tick_time) // self.__tick_interval
        if skipped_ticks:
            tick_time += self.__tick_interval * skipped_ticks
            tick_number += int(skipped_ticks)

        for callback in self.timer_ticked:
            callback(self, now, tick_number)

        tick_time += self.__tick_interval
        self.__tick_timer_handle = self.__event_loop.call_at(self.__start_time + tick_time, self.__on_timer_tick,
                                                             tick_time, tick_number + 1)

    def start(self) -> None:
        """Start this timer."""
        self.__start_time = time.monotonic()
        for callback in self.timer_started:
            callback(self, self.__start_time)
        self.__on_timer_tick(0.0, 1)

    def shutdown(self, now: float, reason: str) -> None:
        """Shut down this timer."""
        self.__logger.info("shutting down the match: time=%.6f reason='%s'", now, reason)
        if self.__tick_timer_handle:
            self.__tick_timer_handle.cancel()
        for callback in self.timer_stopped:
            callback(self, now)
