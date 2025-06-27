"""Tests for Cache of LlmClient class."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile

import pytest

from git_llm_pick.llm_client import instantiate_llm_client


def test_llm_client_creation_from_dict():
    """Test that we can create lLM client from dictionaries."""

    query = "abc"
    answer = "01234567890"

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_json = os.path.join(tmpdir, "cache.json")
        parameter = {"cache_file": cache_json, "temperature": "0.9"}
        client = instantiate_llm_client(parameter)
        # pylint: disable=W0212
        client._update_cache(query=query, answer=answer)
        cached_answer = client.ask(query=query)

        assert cached_answer == answer


def test_llm_client_creation_failure():
    """Test that we properly fail on unknown parameters."""
    parameter = {"unknown_parameter": 0}
    with pytest.raises(RuntimeError):
        _ = instantiate_llm_client(parameter)


def test_llm_client_type_failure():
    """Test that we properly fail on wrong parameter types."""
    parameter = {"cache_file": 0}
    with pytest.raises(TypeError):
        _ = instantiate_llm_client(parameter)

    parameter_t = {"temperature": "zero kelvin"}
    with pytest.raises(ValueError):
        _ = instantiate_llm_client(parameter_t)


def test_llm_client_unknown_type_failure():
    """Test that we properly fail on wrong parameter types."""
    parameter = {"cache_file": {1: 1}}
    with pytest.raises(TypeError):
        _ = instantiate_llm_client(parameter)
