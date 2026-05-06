"""
OpenAI Client for Game Flow Generation.

Provides a simple wrapper around OpenAI API for narrative generation.
"""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI client for game flow generation.

    This client provides a simple .generate(prompt) interface
    for narrative rendering.
    """

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini"):
        """Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (if None, uses settings)
            model: Model to use for generation
        """
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model

        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        self.client = OpenAI(api_key=self.api_key)
        logger.info(f"OpenAI client initialized with model: {self.model}")

    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        max_retries: int = 3,
    ) -> str:
        """Generate text from prompt with retry logic.

        Args:
            prompt: Prompt text
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            max_retries: Maximum retry attempts for malformed responses

        Returns:
            Generated text (JSON string for structured outputs)

        Raises:
            Exception: If generation fails after all retries
        """
        last_error = None
        # Cap retry fan-out on malformed responses / flakes.
        attempts = max(1, min(max_retries, 5))

        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a sports narrative writer. Generate engaging, accurate summaries of game moments. Always respond with valid JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("OpenAI returned empty response")

                # Log response length for debugging truncation issues
                logger.debug(f"OpenAI response length: {len(content)} chars")

                # Validate it's valid JSON
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    # Log the problematic content for debugging
                    logger.warning(
                        f"Malformed JSON content (first 100 chars): {content[:100]!r}"
                    )
                    raise

                if attempt > 0:
                    logger.info(f"OpenAI generation succeeded on attempt {attempt + 1}")

                return content

            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(
                    f"OpenAI returned malformed JSON (attempt {attempt + 1}/{attempts}): {e}"
                )
                # Continue to retry

            except Exception as e:
                last_error = e
                logger.error(
                    f"OpenAI generation failed (attempt {attempt + 1}/{attempts}): {e}"
                )
                # For non-JSON errors, also retry (could be transient API issues)

        logger.error(
            f"OpenAI generation failed after {attempts} attempts: {last_error}"
        )
        raise last_error or Exception("OpenAI generation failed")


def get_openai_client() -> OpenAIClient | None:
    """Get OpenAI client if API key is configured.

    Uses openai_model_summary setting (defaults to gpt-4o) for flow generation.

    Returns:
        OpenAIClient if configured, None otherwise
    """
    settings = get_settings()

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not configured - AI generation disabled")
        return None

    try:
        return OpenAIClient(model=settings.openai_model_summary)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return None
