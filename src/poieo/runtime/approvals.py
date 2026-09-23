"""Tool calls waiting on a person: the run asks, and somebody answers.

A step told to `ask_before` a kind of call stops at each one and waits here,
by the call's id, until a person allows it or not. The daemon makes one of
these for every run it starts and hands the board the other end; a run with
nobody behind it has none, and a step that would ask is answered no.

Design: docs/runtime.md
"""

from __future__ import annotations

import asyncio


class Approvals:
    """The calls of one run that are waiting for a person, by call id."""

    def __init__(self) -> None:
        self._waiting: dict[str, asyncio.Future[bool]] = {}

    def waiting(self) -> list[str]:
        """The calls waiting now, oldest first."""
        return [call for call, answer in self._waiting.items() if not answer.done()]

    async def ask(self, call_id: str, cancel: asyncio.Event | None = None) -> bool:
        """Wait for a person's answer to one call; no, if the run is cancelled first."""
        answer: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiting[call_id] = answer
        waits = {answer}
        stop = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
        if stop is not None:
            waits.add(stop)  # type: ignore[arg-type]
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            return answer.result() if answer.done() else False
        finally:
            if stop is not None:
                stop.cancel()
            self._waiting.pop(call_id, None)

    def answer(self, call_id: str, allowed: bool) -> bool:
        """Answer a waiting call. False when nothing is waiting under that id."""
        answer = self._waiting.get(call_id)
        if answer is None or answer.done():
            return False
        answer.set_result(allowed)
        return True
