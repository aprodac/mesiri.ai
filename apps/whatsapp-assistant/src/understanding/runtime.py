"""Understanding pipeline runtime wiring."""

from __future__ import annotations

import logging
from typing import Any

from mesiri_contracts.common.storage import ObjectStoragePort
from understanding.pipeline import UnderstandingPipeline

logger = logging.getLogger(__name__)


def build_pipeline(
    object_storage: ObjectStoragePort, db: Any, redis_client: Any
) -> UnderstandingPipeline:
    """Construct the understanding pipeline from configured providers."""
    from mesiri.bootstrap.settings import get_settings
    from mesiri_ai.resolver import DynamicAIProviderResolver

    settings = get_settings()

    resolver = DynamicAIProviderResolver(db, redis_client, settings)

    logger.info("Understanding pipeline configured with DynamicAIProviderResolver proxy.")
    return UnderstandingPipeline(
        voice_extraction=resolver,  # type: ignore[arg-type]
        vision=resolver,  # type: ignore[arg-type]
        object_storage=object_storage,
    )
