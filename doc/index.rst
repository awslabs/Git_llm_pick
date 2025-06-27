Git LLM Pick
============

A drop-in replacement for git cherry-pick with LLM-powered conflict resolution.

Git-llm-pick first tries to use git cherry-pick. On failure, it tries to use the patch tool to apply the commit. In case the patch tool fails to apply a commit, an LLM is used to modify and apply the rejected hunks.

Features
--------

* Drop-in replacement for git cherry-pick
* Fuzzy patching with configurable fuzz factors
* LLM-powered conflict resolution using AWS Bedrock
* Path rewriting for cross-codebase porting
* Validation commands for quality assurance

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   _apidoc/modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
