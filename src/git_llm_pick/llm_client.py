#!/usr/bin/env python3

"""
Basic class to interact with LLMs.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger(__name__)


class LlmClient:
    """Simple LLM interface."""

    def __init__(
        self,
        model_id="us.amazon.nova-pro-v1:0",  # Use Nova Pro with US inference profile
        aws_region="us-west-2",
        system_prompts=None,
        temperature=0.0,
        cache_file=None,
        max_token=8192,  # Use more token, to be able to backport more commits
        max_retries=3,  # Maximum number of retry attempts
        retry_delay=1.0,  # Initial retry delay in seconds
    ):
        self._model_id = model_id
        self._region = aws_region
        self._system_prompts = system_prompts
        self._model_temperature = temperature
        self._model_max_token = max_token
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        self._cache_file = cache_file

        self._calls = 0
        self._submitted_words = 0
        self._received_words = 0
        self._input_tokens = 0
        self._output_tokens = 0

        try:
            import boto3
        except ImportError:
            log.error("error: not initializing LLM agent. boto3 not installed")
            return
        try:
            self._bedrock_client = boto3.client("bedrock-runtime", region_name=self._region)
        except Exception as e:
            log.error("error: not initializing LLM agent. Failed to create bedrock client: %r", e)
            return

    def get_stats(self) -> dict:
        return {
            "llm_calls": self._calls,
            "submitted_words_total": self._submitted_words,
            "received_words_total": self._received_words,
            "input_tokens_total": self._input_tokens,
            "output_tokens_total": self._output_tokens,
        }

    def _check_cache(self, query):
        """Check whether we have a cached answer for the given query."""
        log.debug("Checking cache for query %s", query)
        if not self._cache_file:
            return None
        if not os.path.exists(self._cache_file):
            return None
        # Create md5sum hash of the query
        query_hash = hashlib.md5(self._model_id.encode() + query.encode()).hexdigest()
        # Open cache JSON file, and check whether there is an entry of query_hash
        log.debug("Checking cache for query hash %s", query_hash)
        cache_entry = None
        with open(self._cache_file, "r") as f:
            cache = json.load(f)
            cache_entry = cache.get(query_hash)
        if not cache_entry:
            return None
        if cache_entry.get("query", "") == query and cache_entry.get("model_id", "") == self._model_id:
            answer = cache_entry.get("answer", "")
            if answer:
                return answer
        return None

    def _update_cache(self, query, answer):
        """Update the cache with the given query and answer."""
        log.debug("Updating cache for query %s", query)
        if not self._cache_file:
            return
        try:
            # Create md5sum hash of the query
            query_hash = hashlib.md5(self._model_id.encode() + query.encode()).hexdigest()
            # Open cache JSON file, and check whether there is an entry of query_hash
            log.debug("Updating cache for query hash %s", query_hash)
            cache_entry = {"query": query, "answer": answer, "model_id": self._model_id}
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r") as f:
                    cache = json.load(f)
                    cache[query_hash] = cache_entry
            else:
                cache = {query_hash: cache_entry}
            with open(self._cache_file, "w") as f:
                json.dump(cache, f, sort_keys=True)
        except Exception as e:
            log.warning("Failed writing LLM cache file %s with: %r", self._cache_file, e)

    def _is_retryable_error(self, exception) -> bool:
        """Return if an exception is retryable (rate limiting, throttling, temporary failures)."""
        error_str = str(exception).lower()

        # Check for specific AWS error codes that indicate retryable conditions
        retryable_conditions = [
            "throttlingexception",
            "throttled",
            "rate exceeded",
            "too many requests",
            "service unavailable",
            "internal server error",
            "timeout",
            "connection error",
            "temporary failure",
        ]

        return any(condition in error_str for condition in retryable_conditions)

    def _bedrock_request_with_retry(self, query: str) -> Optional[str]:
        """Make a Bedrock request with exponential backoff retry logic."""
        last_exception = None

        if not query:
            log.debug("Skipping empty query")
            return None

        self._calls += 1
        words_to_submit = len(query.split())

        for attempt in range(self._max_retries + 1):  # +1 for initial attempt
            try:
                log.debug("LLM processing query (attempt %d/%d)", attempt + 1, self._max_retries + 1)
                inference_config = {"temperature": self._model_temperature}
                if self._model_max_token is not None:
                    inference_config["maxTokens"] = self._model_max_token

                self._submitted_words += words_to_submit
                response = self._bedrock_client.converse(
                    modelId=self._model_id,
                    messages=[{"role": "user", "content": [{"text": query}]}],
                    system=self._system_prompts if self._system_prompts else [],
                    inferenceConfig=inference_config,
                )

                # Success - return the response
                answer = response["output"]["message"]["content"][0]["text"]
                if attempt > 0:
                    log.debug("LLM request succeeded after %d retries", attempt)
                self._received_words += len(answer.split()) if answer else 0
                used_input_tokens = response.get("usage", {}).get("inputTokens", 0)
                used_output_tokens = response.get("usage", {}).get("outputTokens", 0)
                if not used_input_tokens or not used_output_tokens:
                    log.warning(
                        "Did not find token in output: detected input token: %d output token: %d",
                        used_input_tokens,
                        used_output_tokens,
                    )
                self._input_tokens += used_input_tokens
                self._output_tokens += used_output_tokens
                return answer

            except Exception as e:
                last_exception = e

                if attempt == self._max_retries:
                    break

                # Retry after exponential backoff
                if not self._is_retryable_error(e):
                    log.error("Non-retryable error occurred: %s", e)
                    break

                delay = self._retry_delay * (2**attempt)
                log.warning(
                    "Retryable error occurred (attempt %d/%d): %s. Retrying in %.1f seconds...",
                    attempt + 1,
                    self._max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)

        # All retries exhausted
        log.error("Failed to query bedrock after %d attempts. Last error: %s", attempt + 1, last_exception)
        return None

    def get_model_prefix(self):
        """Return identifier for used model."""
        return self._model_id.split("-")[0] if self._model_id else "uninitialized"

    def ask(self, query: str):
        """Asks the llm for a response given a query and return answer text."""

        log.debug("Submitting query to LLM with %d words", len(query.split()))
        cached_result = self._check_cache(query)
        if cached_result:
            log.debug("Using cached result for query %s", query)
            return cached_result

        answer = self._bedrock_request_with_retry(query)
        if answer is None:
            return None

        if len(answer) > 100:
            self._update_cache(query, answer)
        log.debug("Received LLM answer with %d words", len(answer.split()))
        return answer


def instantiate_llm_client(
    llm_parameter: dict,
) -> LlmClient:
    """This method allows to create an LLM client based on string parameters."""

    # Parameter supported by the model today
    supported_parameter = {
        "model_id": "str",
        "aws_region=": "str",
        "temperature": "float",
        "cache_file": "str",
        "max_token": "int",
        "max_retries": "int",
        "retry_delay": "float",
    }

    # Check for each parameter, whether it is supported and has the right type
    for parameter, value in llm_parameter.items():
        if parameter not in supported_parameter:
            raise RuntimeError(f"LLM parameter {parameter} is not supported by LLM client")

        expected_type = supported_parameter[parameter]

        # Check parameter type
        if expected_type == "str":
            if not isinstance(value, str):
                raise TypeError(f"Parameter {parameter} must be a string")
        elif expected_type == "float":
            # Will throw ValueError, in case the string is of the wrong type
            llm_parameter[parameter] = float(value)
        elif expected_type == "int":
            # Will throw ValueError, in case the string is of the wrong type
            llm_parameter[parameter] = int(value)
        else:
            raise NotImplementedError(f"Expected type '{expected_type}' is not handled")

    return LlmClient(**llm_parameter)
