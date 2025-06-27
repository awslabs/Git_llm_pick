"""Tests for Cache of LlmClient."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile

from git_llm_pick.llm_client import LlmClient


def test_llm_client_caching():
    """Test that a cached answer can be returned."""

    query = "abc"
    answer = "01234567890"

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_json = os.path.join(tmpdir, "cache.json")
        client = LlmClient(cache_file=cache_json)
        # prime cache by using private method
        # pylint: disable=W0212
        client._update_cache(query=query, answer=answer)
        cached_answer = client.ask(query=query)

        assert cached_answer == answer


def test_llm_empty_query():
    """An empty query should result in no answer without using Bedrock, returning None."""

    client = LlmClient()
    obtained_answer = client.ask(query="")
    assert obtained_answer is None
