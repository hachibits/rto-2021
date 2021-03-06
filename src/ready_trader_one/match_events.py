import asyncio
import csv
import enum
import logging
import queue
import threading

from typing import Any, Callable, List, Optional, TextIO

from .types import Instrument, Lifespan, Side


class MatchEventOperation(enum.IntEnum):
    AMEND = 0
    CANCEL = 1
    INSERT = 2
    HEDGE = 3
    TRADE = 4


class MatchEvent:
    __slots__ = ("time", "competitor", "operation", "order_id", "instrument", "side", "volume", "price", "lifespan",
                 "fee")

    OPERATION_NAMES = {o: o.name.capitalize() for o in MatchEventOperation}

    def __init__(self, time: float, competitor: str, operation: MatchEventOperation, order_id: int,
                 instrument: Optional[Instrument], side: Optional[Side], volume: int, price: Optional[int],
                 lifespan: Optional[Lifespan], fee: Optional[int]):
        self.time: float = time
        self.competitor: str = competitor
        self.operation: MatchEventOperation = operation
        self.order_id: int = order_id
        self.instrument: Optional[Instrument] = instrument
        self.side: Optional[Side] = side
        self.volume: int = volume
        self.price: Optional[int] = price
        self.lifespan: Optional[Lifespan] = lifespan
        self.fee: Optional[int] = fee

    def __iter__(self):
        return iter((round(self.time, 6),
                     self.competitor,
                     MatchEvent.OPERATION_NAMES[self.operation],
                     self.order_id,
                     self.instrument.value if self.instrument is not None else None,
                     "AB"[self.side.value] if self.side is not None else None,
                     self.volume,
                     self.price//100 if self.price is not None else None,
                     "FG"[self.lifespan.value] if self.lifespan is not None else None,
                     self.fee/100.0 if self.fee is not None else None))


class MatchEvents:
    """A clearing house of match events."""

    def __init__(self):
        """Initialise a new instance of the MatchEvents class."""
        self.logger = logging.getLogger("MATCH_EVENTS")

        # Callbacks
        self.event_occurred: List[Callable[[MatchEvent], None]] = list()

    def amend(self, now: float, name: str, order_id: int, diff: int) -> None:
        """Create a new amend event."""
        event = MatchEvent(now, name, MatchEventOperation.AMEND, order_id, None, None, diff, None, None, None)
        for callback in self.event_occurred:
            callback(event)

    def cancel(self, now: float, name: str, order_id: int, diff: int) -> None:
        """Create a new cancel event."""
        event = MatchEvent(now, name, MatchEventOperation.CANCEL, order_id, None, None, diff, None, None, None)
        for callback in self.event_occurred:
            callback(event)

    def fill(self, now: float, name: str, order_id: int, instrument: Instrument, side: Side, price: int, diff: int,
             fee: int) -> None:
        """Create a new fill event."""
        for callback in self.event_occurred:
            callback(MatchEvent(now, name, MatchEventOperation.TRADE, order_id, instrument, side, diff, price,
                                None, fee))

    def hedge(self, now: float, name: str, order_id: int, instrument: Instrument, side: Side, price: int,
              volume: int) -> None:
        """Create a new fill event."""
        for callback in self.event_occurred:
            callback(MatchEvent(now, name, MatchEventOperation.HEDGE, order_id, instrument, side, volume, price,
                                None, None))

    def insert(self, now: float, name: str, order_id: int, instrument: Instrument, side: Side, volume: int,
               price: int, lifespan: Lifespan) -> None:
        """Create a new insert event."""
        event = MatchEvent(now, name, MatchEventOperation.INSERT, order_id, instrument, side, volume, price,
                           lifespan, None)
        for callback in self.event_occurred:
            callback(event)


class MatchEventsWriter:
    """A processor of match events that it writes to a file."""

    def __init__(self, match_events: MatchEvents, filename: str, loop: asyncio.AbstractEventLoop):
        """Initialise a new instance of the MatchEvents class."""
        self.event_loop: asyncio.AbstractEventLoop = loop
        self.filename: str = filename
        self.finished: bool = False
        self.logger = logging.getLogger("MATCH_EVENTS")
        self.match_events: MatchEvents = match_events
        self.queue: queue.Queue = queue.Queue()
        self.writer_task: Optional[threading.Thread] = None

        match_events.event_occurred.append(self.queue.put)

        # Callbacks
        self.task_complete: List[Callable[[Any], None]] = list()

    def __del__(self):
        """Destroy an instance of the MatchEvents class."""
        if not self.finished:
            self.finish()
        self.writer_task.join()

    def finish(self) -> None:
        """Indicate the the series of events is complete."""
        self.match_events.event_occurred.remove(self.queue.put)
        self.queue.put(None)
        self.finished = True

    def on_writer_done(self, num_events: int) -> None:
        """Called when the match event writer thread is done."""
        for c in self.task_complete:
            c(self)
        self.logger.info("writer thread complete after processing %d match events", num_events)

    def start(self):
        """Start the match events writer thread"""
        try:
            match_events_file = open(self.filename, "w", newline="")
        except IOError as e:
            self.logger.error("failed to open match events file: filename=%s", self.filename, exc_info=e)
            raise
        else:
            self.writer_task = threading.Thread(target=self.writer, args=(match_events_file,), daemon=False,
                                                name="match_events")
            self.writer_task.start()

    def writer(self, match_events_file: TextIO) -> None:
        """Fetch match events from a queue and write them to a file"""
        count = 0
        fifo = self.queue

        try:
            with match_events_file:
                csv_writer = csv.writer(match_events_file)
                csv_writer.writerow(("Time,Competitor,Operation,OrderId,Instrument,Side,Volume,Price,Lifespan,"
                                     "Fee").split(','))

                evt: MatchEvent = fifo.get()
                while evt is not None:
                    count += 1
                    csv_writer.writerow(evt)
                    evt = fifo.get()
        finally:
            if not self.event_loop.is_closed():
                self.event_loop.call_soon_threadsafe(self.on_writer_done, count)
