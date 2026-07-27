"""
Step 1: Tweak Extraction & Parsing

This module extracts structured modifications from review text using LLM processing.
It converts natural language descriptions of recipe changes into structured
ModificationObject instances.
"""

import json
import os
from collections.abc import Iterable
from typing import Optional

from loguru import logger
from openai import OpenAI
from pydantic import ValidationError

from .env_loader import load_project_env
from .models import ModificationObject, ModificationSet, Recipe, Review
from .prompts import build_simple_prompt
from .tip_eligibility import select_candidate_reviews


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.5-flash",
    "dashscope": "qwen3.7-plus",
}

DEFAULT_BASE_URLS = {
    "openai": None,
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    # International (Singapore) OpenAI-compatible endpoint; override with LLM_BASE_URL if needed.
    "dashscope": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}

PROVIDER_ALIASES = {
    "alibaba": "dashscope",
    "qwen": "dashscope",
    "aliyun": "dashscope",
}


class TweakExtractor:
    """Extracts structured modifications from review text using LLM processing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the TweakExtractor.

        Args:
            api_key: Provider API key (defaults to env var for configured provider)
            model: Model to use for extraction
            provider: LLM provider, one of "openai", "gemini", or "dashscope"
            base_url: Optional base URL override for OpenAI-compatible providers
        """
        load_project_env()
        self.provider = self.resolve_provider(provider)
        self.api_key = api_key or self.resolve_api_key(self.provider)
        self.base_url = base_url or self.resolve_base_url(self.provider)
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODELS[self.provider]

        if not self.api_key:
            raise ValueError(
                "No LLM API key configured. Set DASHSCOPE_API_KEY (or QWEN_API_KEY) for "
                "Alibaba Model Studio, GEMINI_API_KEY for Google AI Studio, or OPENAI_API_KEY."
            )

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)
        logger.info(
            f"Initialized TweakExtractor with provider={self.provider}, model={self.model}"
        )

    @staticmethod
    def resolve_provider(provider: Optional[str]) -> str:
        resolved_provider = (provider or os.getenv("LLM_PROVIDER") or "").strip().lower()
        if resolved_provider:
            resolved_provider = PROVIDER_ALIASES.get(resolved_provider, resolved_provider)
            if resolved_provider not in DEFAULT_MODELS:
                raise ValueError(
                    "Unsupported LLM provider "
                    f"'{resolved_provider}'. Use 'openai', 'gemini', or 'dashscope'."
                )
            return resolved_provider

        if os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or os.getenv(
            "QWAN_API_KEY"
        ) or os.getenv("ALIBABA_API_KEY"):
            return "dashscope"
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        return "openai"

    @staticmethod
    def resolve_api_key(provider: str) -> Optional[str]:
        if provider == "gemini":
            return os.getenv("GEMINI_API_KEY")
        if provider == "dashscope":
            return (
                os.getenv("DASHSCOPE_API_KEY")
                or os.getenv("ALIBABA_API_KEY")
                or os.getenv("QWEN_API_KEY")
                or os.getenv("QWAN_API_KEY")  # common typo alias in local env
            )
        return os.getenv("OPENAI_API_KEY")

    @staticmethod
    def resolve_base_url(provider: str) -> Optional[str]:
        return os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URLS[provider]

    @staticmethod
    def _parse_modification_set_payload(raw_output: str) -> list[ModificationObject]:
        modification_data = json.loads(raw_output)

        if isinstance(modification_data, list):
            return [ModificationObject(**item) for item in modification_data]

        if isinstance(modification_data, dict):
            if "modifications" in modification_data:
                return ModificationSet(**modification_data).modifications
            # Backward-compatible single-object payloads from older prompts/models.
            return [ModificationObject(**modification_data)]

        raise ValueError(
            f"Unexpected modification payload type: {type(modification_data)!r}"
        )

    def _extract_with_raw_completion(self, prompt: str) -> list[ModificationObject]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2000,
        )

        raw_output = response.choices[0].message.content
        logger.debug(f"LLM raw output: {raw_output}")

        if not raw_output:
            return []

        return self._parse_modification_set_payload(raw_output)

    def extract_modifications_from_review(
        self,
        review: Review,
        recipe: Recipe,
        max_retries: int = 2,
    ) -> list[ModificationObject]:
        """
        Extract all discrete modifications clearly stated in one review.
        """
        # Candidate selection happens upstream; do not hard-refuse on the scraper hint.
        if not review.has_modification:
            logger.debug(
                "Review lacks scraper has_modification hint; extracting anyway as candidate"
            )

        prompt = build_simple_prompt(
            review.text, recipe.title, recipe.ingredients, recipe.instructions
        )

        logger.debug(
            "Extracting modifications from review: {}...".format(review.text[:100])
        )

        for attempt in range(max_retries + 1):
            raw_output = None
            try:
                parsed_message = self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=ModificationSet,
                    temperature=0.1,
                    max_tokens=2000,
                )

                parsed_set = parsed_message.choices[0].message.parsed
                if parsed_set is not None:
                    modifications = parsed_set.modifications
                else:
                    raw_output = parsed_message.choices[0].message.content
                    logger.debug(f"LLM raw output: {raw_output}")

                    if not raw_output:
                        logger.warning(f"Attempt {attempt + 1}: Empty response from LLM")
                        continue

                    modifications = self._parse_modification_set_payload(raw_output)

                logger.info(
                    f"Successfully extracted {len(modifications)} discrete "
                    f"modification(s) from one review"
                )
                return modifications

            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to parse JSON: {e}")
                if attempt == max_retries:
                    logger.error(f"Max retries reached. Raw output: {raw_output}")

            except ValidationError as e:
                logger.warning(f"Attempt {attempt + 1}: Validation error: {e}")
                if attempt == max_retries:
                    logger.error("Max retries reached due to invalid modification data")

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}: Structured parse failed, falling back to raw JSON extraction: {e}"
                )

                try:
                    modifications = self._extract_with_raw_completion(prompt)
                    logger.info(
                        f"Successfully extracted {len(modifications)} discrete "
                        f"modification(s) via raw fallback"
                    )
                    return modifications
                except (json.JSONDecodeError, ValidationError, ValueError) as fallback_error:
                    logger.warning(
                        f"Attempt {attempt + 1}: Raw fallback parse failed: {fallback_error}"
                    )
                except Exception as fallback_error:
                    logger.error(
                        f"Attempt {attempt + 1}: Raw fallback unexpected error: {fallback_error}"
                    )

                if attempt == max_retries:
                    return []

        return []

    def extract_modification(
        self,
        review: Review,
        recipe: Recipe,
        max_retries: int = 2,
    ) -> Optional[ModificationObject]:
        """
        Extract the first discrete modification from a review.

        Prefer extract_modifications_from_review when multiple tips may exist.
        """
        modifications = self.extract_modifications_from_review(
            review, recipe, max_retries=max_retries
        )
        return modifications[0] if modifications else None

    def extract_single_modification(
        self, reviews: list[Review], recipe: Recipe
    ) -> tuple[ModificationObject, Review] | tuple[None, None]:
        """
        Extract modification from a single randomly selected review.

        Args:
            reviews: List of reviews to choose from
            recipe: Original recipe being modified

        Returns:
            Tuple of (ModificationObject, source_Review) if successful, (None, None) otherwise
        """
        import random

        modification_reviews = select_candidate_reviews(reviews)

        if not modification_reviews:
            logger.warning("No extraction-candidate reviews found")
            return None, None

        selected_review = random.choice(modification_reviews)
        logger.info(f"Selected review: {selected_review.text[:100]}...")

        modifications = self.extract_modifications_from_review(selected_review, recipe)
        if modifications:
            logger.info("Successfully extracted modification from selected review")
            return modifications[0], selected_review

        logger.warning("Failed to extract modification from selected review")
        return None, None

    def extract_modifications(
        self,
        reviews: Iterable[Review],
        recipe: Recipe,
        max_reviews: Optional[int] = None,
    ) -> list[tuple[ModificationObject, Review]]:
        """
        Extract structured modifications from multiple reviews.

        Each review may contribute multiple discrete modifications.
        """
        extracted_modifications: list[tuple[ModificationObject, Review]] = []

        for index, review in enumerate(reviews):
            if max_reviews is not None and index >= max_reviews:
                break

            modifications = self.extract_modifications_from_review(review, recipe)
            if modifications:
                for modification in modifications:
                    extracted_modifications.append((modification, review))
            else:
                logger.warning(
                    "Skipping review after failed extraction: {}...".format(
                        review.text[:100]
                    )
                )

        logger.info(
            f"Successfully extracted {len(extracted_modifications)} modifications from review set"
        )
        return extracted_modifications

    def test_extraction(
        self, review_text: str, recipe_data: dict
    ) -> Optional[ModificationObject]:
        """
        Test extraction with raw text and recipe data.

        Args:
            review_text: Raw review text
            recipe_data: Raw recipe dictionary

        Returns:
            ModificationObject if successful
        """
        review = Review(text=review_text, has_modification=True)
        recipe = Recipe(
            recipe_id=recipe_data.get("recipe_id", "test"),
            title=recipe_data.get("title", "Test Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
        )

        return self.extract_modification(review, recipe)
