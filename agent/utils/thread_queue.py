"""Shared utility for queuing messages to LangGraph agent threads."""

from __future__ import annotations

import logging
from typing import Any

from langgraph_sdk import get_client

logger = logging.getLogger(__name__)


async def queue_message_for_thread(
    thread_id: str,
    message_content: str | list[dict[str, Any]] | dict[str, Any],
    langgraph_url: str | None = None,
) -> bool:
    """Queue a message for delivery to an agent thread before its next model call.

    Stores the message in the LangGraph store, namespaced to the thread.
    The before_model middleware (check_message_queue_before_model) picks it up
    and injects it as a human message, re-activating the agent loop.

    Args:
        thread_id: The LangGraph thread ID.
        message_content: Text string or content block(s) to queue.
        langgraph_url: LangGraph server URL. Defaults to localhost if not given.

    Returns:
        True if successfully queued, False on error.
    """
    langgraph_client = get_client(url=langgraph_url)
    namespace = ("queue", thread_id)
    key = "pending_messages"

    try:
        existing_messages: list[dict[str, Any]] = []
        try:
            existing_item = await langgraph_client.store.get_item(namespace, key)
            if existing_item and existing_item.get("value"):
                existing_messages = existing_item["value"].get("messages", [])
        except Exception:  # noqa: BLE001
            logger.debug("No existing queued messages for thread %s", thread_id)

        existing_messages.append({"content": message_content})
        await langgraph_client.store.put_item(namespace, key, {"messages": existing_messages})
        logger.info(
            "Queued message for thread %s (total queued: %d)", thread_id, len(existing_messages)
        )
        return True  # noqa: TRY300
    except Exception:
        logger.exception("Failed to queue message for thread %s", thread_id)
        return False
