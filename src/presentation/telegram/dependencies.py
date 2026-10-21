"""What the Telegram handlers need from the outside world, as a contract.

Handlers never construct adapters themselves. They receive a
``UseCaseProvider`` (workflow data key ``use_cases``) plus domain ports
(``preview_store``, ``rate_limiter``, ``health_check``,
``ping_result_reader``), all built once in the composition root
(``src/main.py`` + ``src/composition.py``). This module is the only thing
presentation knows about that wiring — it names application use cases and
nothing from ``src.infrastructure``.

Use cases that touch the database are handed out as async context
managers: one ``async with`` is one unit of work (commit on success,
rollback on exception), exactly the transaction boundary the handlers had
when they opened sessions themselves.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.application.use_cases.register_user import RegisterUserUseCase
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.application.use_cases.set_user_language import SetUserLanguageUseCase
from src.application.use_cases.trigger_ping_job import TriggerPingJobUseCase


class UseCaseProvider(Protocol):
    def register_user(self) -> AbstractAsyncContextManager[RegisterUserUseCase]: ...

    def request_download(self) -> AbstractAsyncContextManager[RequestDownloadUseCase]: ...

    def set_user_language(self) -> AbstractAsyncContextManager[SetUserLanguageUseCase]: ...

    def preview_download(self) -> PreviewDownloadUseCase: ...

    def trigger_ping_job(self) -> TriggerPingJobUseCase: ...
