"""
Module implementing matching on patches and hunks using LLMs.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import difflib
import glob
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List

from git_llm_pick import (
    LLM_ADJUST_EXTRA_CONTEXT_LINES,
    MAX_ADJUST_SECTION_LENGTH_DIFFERENCE,
    NO_SECTION_HUNK_EXTRA_CONTEXT,
)
from git_llm_pick.git_commands import commit_function_location, get_commit_message
from git_llm_pick.llm_client import instantiate_llm_client
from git_llm_pick.llm_scripts import (
    ADAPTED_SNIPPET_HEADER,
    SUMMARY_SECTION_HEADER,
    get_hunk_patching_template,
    get_section_patching_template,
)
from git_llm_pick.markdown_parser import MarkdownFlatParser
from git_llm_pick.patch_matching import find_section_header_of_matching_hunk, parse_commit_hunks
from git_llm_pick.utils import code_section_location, get_file_lines, string_edit_distance

log = logging.getLogger(__name__)


def generate_nonce() -> str:
    """Generate a random nonce for LLM queries."""
    return os.urandom(19).hex()


def validate_extracted_llm_content(content: str, content_type: str) -> bool:
    """Validate extracted code or explanation content from LLM output."""
    if not content:
        return True  # Empty content is acceptable

    # Start with a very restrictive set. Based on use-case, the pattern can be extended
    # Validate character sets (ASCII printable + whitespace)
    allowed_chars_regex = r"^[\x20-\x7E\n\r\t‘’]*$"
    if not re.match(allowed_chars_regex, content):
        log.error("LLM %s contains invalid characters (non-ASCII printable)", content_type)
        return False

    return True


class RejectedPatch:
    """Represents a rejected patch file and its hunks."""

    def __init__(self, rej_file_path: str):
        """On failure, throws an exception, and object cannot be used afterwards."""
        try:
            from unidiff import PatchSet
        except Exception as e:
            log.warning("unidiff is not installed, cannot parse rejected hunks")
            raise RuntimeError("unidiff is not installed, cannot parse rejected hunks") from e
        self.rej_file_path = rej_file_path

        self._patch = PatchSet.from_filename(self.rej_file_path, encoding="utf-8")
        if len(self._patch) != 1:
            raise ValueError("Rejected patch must have exactly one patch")
        self.target_file_lines = get_file_lines(self._patch[0].target_file)

    def __str__(self):
        return f"RejectedPatch(file={self._patch[0].source_file}, " f"hunks={len(self.hunks())})"

    def target_file(self):
        return self._patch[0].target_file

    def patch(self):
        """Return patch object."""
        return str(self._patch)

    def remove_file(self):
        """Remove the rejected patch file."""
        log.debug("Removing patch reject file %s", self.rej_file_path)
        os.remove(self.rej_file_path)

    def hunks(self):
        """Return the hunks in the patch."""
        return self._patch[0]


def find_all_rejected_patches(directory: str = ".") -> List[RejectedPatch]:
    """Find all rejected patches from .rej files."""
    all_failed_patches = []

    # Find all .rej files
    for rej_file in glob.glob(f"{directory}/**/*.rej", recursive=True):
        try:
            rejected_patch = RejectedPatch(rej_file)
            all_failed_patches.append(rejected_patch)
        except Exception as e:
            print(f"Error processing rejected file {rej_file}: {e}")

    return all_failed_patches


@dataclass
class LlmLimits:
    """Settings how to limit LLM output."""

    limit_interactive: bool = False
    llm_limit_char_diff: int = -1
    llm_limit_diff_ratio: float = -1
    llm_filter_phrases: list = field(default_factory=list)
    llm_input_lines: int = 0

    def any_pre(self) -> bool:
        """Return if any of the given limits for pre-generation is set."""
        return any([self.llm_filter_phrases]) or self.llm_input_lines != 0

    def any_post(self) -> bool:
        """Return if any of the given limits for post-generation is set."""
        return self.limit_interactive or self.llm_limit_char_diff >= 0 or self.llm_limit_diff_ratio >= 0


def ask_user_approval(original_change: str, llm_change: str):
    """Ask user for approval of the LLM change."""

    print(f"\n### Original change:\n\n{original_change}\n\n")
    print(f"\n### LLM-proposed change:\n\n{llm_change}\n\n")

    while True:
        user_input = input("Do you want to apply the above LLM change? (y/n): ")
        if user_input.lower() in ["yes", "y"]:
            return True
        elif user_input.lower() in ["no", "n"]:
            return False
        else:
            print("Invalid input. Please enter yes/no.")


def validate_llm_input(llm_limits, llm_query, hunk_input_lines):
    """Return false, if configured limits would stop processing input."""
    if llm_limits.llm_filter_phrases:
        for phrase in llm_limits.llm_filter_phrases:
            if phrase.lower() in llm_query.lower():
                log.error("Detected filter phrase in input to LLM, aborting. Phrase: %s", phrase)
                return False

    if llm_limits.llm_input_lines != 0:
        if llm_limits.llm_input_lines < hunk_input_lines:
            log.error(
                "Detected too many lines in the input (%d instead of %d), rejecting input",
                hunk_input_lines,
                llm_limits.llm_input_lines,
            )
            return False

    return True


def validate_llm_output(llm_limits: LlmLimits, original_hunk_lines: list, llm_hunk_lines: list) -> bool:
    """Validate llm output based on specified limits"""

    if llm_limits.llm_limit_diff_ratio >= 0 or llm_limits.llm_limit_char_diff > 0:
        relevant_hunk_lines = [x for x in original_hunk_lines if x.startswith("-") or x.startswith("+")]
        relevant_llm_lines = [x for x in llm_hunk_lines if x.startswith("-") or x.startswith("+")]
        llm_text = "\n".join(relevant_llm_lines)
        distance = string_edit_distance("\n".join(relevant_hunk_lines), llm_text)
        distance_ratio = float(distance) / len(llm_text) if llm_text else 0
        log.info(
            "Checking LLM hunk with edit distance %d and relative distance %f",
            distance,
            distance_ratio,
        )
        if (llm_limits.llm_limit_diff_ratio >= 0 and distance_ratio > llm_limits.llm_limit_diff_ratio) or (
            llm_limits.llm_limit_char_diff >= 0 and distance > llm_limits.llm_limit_char_diff
        ):
            log.error(
                "Detected change with edit distance %d and ratio %f, while only distance %d and ratio %f is allowed",
                distance,
                distance_ratio,
                llm_limits.llm_limit_char_diff,
                llm_limits.llm_limit_diff_ratio,
            )
            return False

    if llm_limits.limit_interactive:
        if not ask_user_approval("\n".join(original_hunk_lines), "\n".join(llm_hunk_lines)):
            return False
    return True


class LlmPatcher:
    """Use LLM to adapt patches to apply to current repository state."""

    def __init__(self, llm_parameters: str = "", llm_limits: LlmLimits = None) -> None:

        self.llm_parameters = llm_parameters
        self._llm_client = None

        self.llm_limits = llm_limits if llm_limits is not None else LlmLimits()

    def llm_client(self):
        """Create llm_client member lazily."""

        if not self._llm_client:
            llm_parameters_dict = {}
            if self.llm_parameters:
                llm_parameter_parts = self.llm_parameters.split(",")
                for part in llm_parameter_parts:
                    if "=" not in part:
                        raise ValueError(f"Expected '=' sign in part {part} of {self.llm_parameters}")
                    key, value = part.split("=", 1)
                    llm_parameters_dict[key] = value
            log.info("Received parameters for the LlmClient: %r", llm_parameters_dict)
            self._llm_client = instantiate_llm_client(llm_parameters_dict)
        return self._llm_client

    def apply_hunks_with_empty_section(
        self, hunks_with_empty_section: list, patch_target_file: str, commit_message: str
    ):
        """Apply LLM suggested changes to hunks without section header."""

        show_extra_context_lines = NO_SECTION_HUNK_EXTRA_CONTEXT  # to help generate a better patch

        log.info(
            "Adjusting %d hunks without section header for file %s", len(hunks_with_empty_section), patch_target_file
        )

        hunk_messages = []
        for hunk in hunks_with_empty_section:
            # Extract the hunk content
            hunk_content = str(hunk)
            log.debug("Hunk content: %s", hunk_content)

            with open(patch_target_file, "r") as target_file:
                file_content = target_file.read()
                target_file_lines = file_content.splitlines(keepends=True)

            patch_line = -1
            patch_line_map = {}
            for line in hunk.source:  # For now, consider full file. In future, only consider window
                patch_line += 1
                hitline = None
                test_line = line.strip()
                if not test_line:
                    continue
                index = 0
                for target_line in target_file_lines:
                    index += 1
                    target_line = target_line.strip()
                    if target_line == test_line:
                        if hitline is not None:
                            hitline = -1
                            break
                        hitline = index
                if hitline is None:
                    log.debug("Count not find line: %s", line)
                elif hitline == -1:
                    log.debug("Found line multiple times: %s", line)
                else:
                    log.debug("Found patch line %d (%s) once at line %d", patch_line, line, hitline)
                    patch_line_map[hunk.source_start + patch_line] = hitline

            # find a line in the hunk that also exists in the current file, once
            # use the line numbers to calculate a patch hunk offset
            log.debug("Found lines from patch in target file: %r", patch_line_map)

            if not patch_line_map:
                log.info("Did not find a matching line between hunk and file, aborting ...")
                return False, "Did not find any line of the patch in the source file", None

            patch_offset = 0
            first_match_lines = sorted(patch_line_map)[0]
            patch_offset = first_match_lines - patch_line_map[first_match_lines]
            log.debug("Detected patch offset %d", patch_offset)

            hunk.source_start -= patch_offset
            hunk.target_start -= patch_offset

            start_line = max(hunk.source_start - show_extra_context_lines, 1)
            end_line = min(hunk.source_start + hunk.source_length + show_extra_context_lines, len(target_file_lines))

            for index in range(start_line, end_line):
                line = target_file_lines[index - 1].rstrip()
                log.debug("Target file line %d: %s", index, line)

            file_context = ""
            for index in range(start_line, end_line):
                file_context += "{:>5}  {}\n".format(index, target_file_lines[index - 1].rstrip())

            # Construct query from template with replacements
            q_template = get_hunk_patching_template()
            nonce = generate_nonce()
            q = q_template.format(
                PROMPT_NONCE=nonce,
                COMMIT_MESSAGE=commit_message,
                REJECTED_HUNK_CONTENT=hunk,
                SOURCE_FILE_NAME=patch_target_file,
                SOURCE_FUNCTION=file_context,
            )

            log.debug("Attempting to patch hunk with %d lines", end_line - start_line)
            if self.llm_limits.any_pre():
                if not validate_llm_input(self.llm_limits, q, end_line - start_line):
                    return False, "Detected LLM input that cannot be processed due to limits", None
                else:
                    log.debug("LLM input passed validation for hunk")

            log.debug("Query to LLM:\n%s", q)
            llm_answer = self.llm_client().ask(q)
            log.debug("LLM answer:\n%s", llm_answer)

            if not llm_answer:
                return False, "Failed to receive an answer from the LLM", None

            # Validate that LLM response doesn't contain the nonce
            if nonce in llm_answer:
                log.error("LLM response contains nonce value, rejecting response")
                return False, "LLM response contains nonce value", None

            for match_prefix in ["##", "**"]:
                markdown_parser = MarkdownFlatParser(llm_answer, section_marker_prefix=match_prefix)
                log.debug("Obtained sections from LLM: %r", markdown_parser.get_all_sections())
                patched_code_section = markdown_parser.get_markdown_section(ADAPTED_SNIPPET_HEADER)
                if patched_code_section:
                    break
            if not patched_code_section:
                log.warning("LLM answer does not contain a patched code section")
                return (
                    False,
                    "LLM answer does not contain section with patched code",
                    None,
                )

            # Validate extracted code section
            if not validate_extracted_llm_content(patched_code_section, "code"):
                return (
                    False,
                    "LLM code section contains invalid content",
                    None,
                )

            patched_code_section_lines = patched_code_section.splitlines()
            patched_code_lines = []
            found_code = False
            for line in patched_code_section_lines:
                if line.strip().startswith("```"):
                    if not found_code:
                        found_code = True
                        continue
                    else:
                        break
                if found_code:
                    patched_code_lines.append(line)
            if not patched_code_lines:
                return False, "Failed to detect code in LLM response", None

            # We construct the input file_context with '{:>5}  {}', hence, we need to remove at least 7 symbols
            patched_code_lines = [x[7:].rstrip() for x in patched_code_lines]

            if self.llm_limits.any_post():
                llm_generated_hunk = list(
                    difflib.unified_diff(
                        [x.rstrip() for x in target_file_lines[start_line - 1 : end_line - 1]], patched_code_lines, n=3
                    )
                )
                if (
                    len(llm_generated_hunk) > 2
                    and llm_generated_hunk[0].startswith("---")
                    and llm_generated_hunk[1].startswith("+++")
                ):
                    llm_generated_hunk = llm_generated_hunk[2:]
                if not validate_llm_output(self.llm_limits, str(hunk).splitlines(), llm_generated_hunk):
                    return False, "Proposed LLM change was rejected by limits", None
                else:
                    log.debug("LLM output passed validation for hunk")

            # Rewrite source file and replace current code with patched code
            with open(patch_target_file, "w") as write_file:
                log.info("Updating content of file %s", patch_target_file)
                for index in range(1, start_line):
                    write_file.write(target_file_lines[index - 1])
                for line in patched_code_lines:
                    write_file.write(line + "\n")  # LLM suggested line without number prefix
                for index in range(end_line, len(target_file_lines) + 1):
                    write_file.write(target_file_lines[index - 1])

            llm_explanation = markdown_parser.get_markdown_section(SUMMARY_SECTION_HEADER)
            if not llm_explanation:
                llm_explanation = "LLM fix for headerless hunk -- failed to extract change summary from LLM"

            # Validate extracted explanation section
            if not validate_extracted_llm_content(llm_explanation, "explanation"):
                return (
                    False,
                    "LLM explanation section contains invalid content",
                    None,
                )
            log.debug("Received LLM answer commit part: %r", llm_explanation)
            hunk_messages.append(llm_explanation)

        return True, "", hunk_messages

    def adjust_rejected_patches_with_llm(self, pick_commit: str):
        """For all rejected hunk files in the directory, adjust hunk and attempt to re-apply."""

        # Re-iterate hunks, collect hunks by function that is fixed, ask LLM for new function for each hunk
        rejected_patches = find_all_rejected_patches()
        if not rejected_patches:
            log.error("Failed to parse rejected files, aborting")
            return False, "Failed to parse rejected files", None
        log.info("Found %d rejected hunk files for massaging functions in hunk with LLM", len(rejected_patches))

        commit_message = get_commit_message(pick_commit)

        last_line_newline = False

        modification_explanations = []
        extra_context = LLM_ADJUST_EXTRA_CONTEXT_LINES
        nonempty_hunk_section_map = defaultdict(list)

        # lazy loading for original commit hunks - only parse when needed
        original_commit_hunks = None

        for rejected_patch in rejected_patches:
            if not rejected_patch.target_file().endswith(".c") and not rejected_patch.target_file().endswith(".h"):
                return False, "Cannot handle patches to non-source files, rejecting.", None

            with open(rejected_patch.target_file(), "r", encoding="utf-8") as source_file:
                file_content = source_file.read()
                dst_source_file_lines = file_content.splitlines()
                last_line_newline = file_content.endswith("\n")
            log.debug(
                "Parsed current source file %s with %d lines", rejected_patch.target_file(), len(dst_source_file_lines)
            )

            nonempty_hunk_section_map.clear()
            hunks_with_empty_section = []
            for hunk in rejected_patch.hunks():
                # check if section header is missing and attempt to recover it from original commit
                if not hunk.section_header or not hunk.section_header.strip():
                    # lazy load original commit hunks only when needed
                    if original_commit_hunks is None:
                        log.debug("Loading original commit hunks for section header recovery")
                        original_commit_hunks = parse_commit_hunks(pick_commit)
                        if original_commit_hunks is None:
                            log.warning("Failed to parse original commit hunks, cannot recover section headers")
                            original_commit_hunks = {}  # Set to empty dict to avoid repeated attempts

                    # try to find matching hunk with section header
                    if original_commit_hunks:
                        original_hunks_for_file = original_commit_hunks.get(rejected_patch.target_file(), [])
                        recovered_section_header = find_section_header_of_matching_hunk(hunk, original_hunks_for_file)
                        if recovered_section_header:
                            log.info(
                                "Recovered section header '%s' for hunk at line %d",
                                recovered_section_header,
                                hunk.source_start,
                            )
                            hunk.section_header = recovered_section_header

                if hunk.section_header and hunk.section_header.strip():
                    nonempty_hunk_section_map[hunk.section_header].append(hunk)
                else:
                    hunks_with_empty_section.append(hunk)

            for section_header in sorted(
                nonempty_hunk_section_map.keys(),
                key=lambda x: nonempty_hunk_section_map[x][0].source_start,
                reverse=True,
            ):

                log.debug("Processing hunks with header '%s'", section_header)
                # find function start and end for source and destination version of the affected file in rejected_patch
                log.debug("Retrieve function definition for pick commit %s", pick_commit + "^")
                try:
                    src_function_start, src_function_end, src_file_lines = commit_function_location(
                        rejected_patch.target_file(), section_header, pick_commit + "^"
                    )
                except RuntimeError:
                    log.warning(
                        "Failed to retrieve function definition for %s in pick commit %s",
                        section_header,
                        pick_commit + "^",
                    )
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                log.debug("Retrieve function definition '%s' for local file %s", section_header, dst_source_file_lines)
                try:
                    dst_function_start, dst_function_end, dst_source_file_lines = code_section_location(
                        section_header, dst_source_file_lines
                    )  # read partially modified file
                    log.debug(
                        "Retrieve function definition for local file and retrieved %d line (%d all lines)",
                        len(dst_source_file_lines),
                        len(dst_source_file_lines),
                    )
                except RuntimeError:
                    log.info(
                        "Failed to find changed code with section '%s', re-trying with hunk-based approach",
                        section_header,
                    )
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                src_function_len = src_function_end - src_function_start
                dst_function_len = dst_function_end - dst_function_start

                if abs(dst_function_len - src_function_len) > MAX_ADJUST_SECTION_LENGTH_DIFFERENCE:
                    log.warning("Function length difference is too large, not supported yet")
                    return (
                        False,
                        f"Function length difference is too large ({src_function_len} in src, {dst_function_len} in dst), not supported yet",
                        None,
                    )

                context_src_function_start = max(0, src_function_start - extra_context)
                context_src_function_end = min(len(src_file_lines), src_function_end + extra_context)
                context_dst_function_start = max(0, dst_function_start - extra_context)
                context_dst_function_end = min(len(dst_source_file_lines), dst_function_end + extra_context)

                log.debug(
                    "Function in source version:\n%s",
                    "\n".join(src_file_lines[context_src_function_start:context_src_function_end]),
                )
                log.debug(
                    "Function in destination version:\n%s",
                    "\n".join(dst_source_file_lines[context_dst_function_start:context_dst_function_end]),
                )

                rejected_hunk_content = ""
                for hunk in nonempty_hunk_section_map[section_header]:
                    rejected_hunk_content = rejected_hunk_content + "\n" + str(hunk)

                q_template = get_section_patching_template()
                nonce = generate_nonce()
                q = q_template.format(
                    PROMPT_NONCE=nonce,
                    COMMIT_MESSAGE=commit_message,
                    SOURCE_FILE_NAME=rejected_patch.target_file(),
                    REJECTED_HUNK_CONTENT=rejected_hunk_content,
                    DESTINATION_FUNCTION="\n".join(
                        dst_source_file_lines[context_dst_function_start:context_dst_function_end]
                    ),
                    SOURCE_FUNCTION="\n".join(src_file_lines[context_src_function_start:context_src_function_end]),
                )
                if self.llm_limits.any_pre():
                    if not validate_llm_input(
                        self.llm_limits, q, context_dst_function_end - context_dst_function_start
                    ):
                        return False, "Detected LLM input that cannot be processed due to limits", None
                    else:
                        log.debug("LLM input passed validation for code section")
                log.debug(
                    "Attempting to patch destination section with %d lines",
                    context_dst_function_end - context_dst_function_start,
                )
                log.debug("Query to LLM:\n%s", q)
                llm_answer = self.llm_client().ask(q)
                log.debug("LLM answer:\n%s", llm_answer)

                if not llm_answer:
                    log.info(
                        "Failed to receive an answer from the LLM, forwarding %d hunks to be processed on hunk level",
                        len(nonempty_hunk_section_map[section_header]),
                    )
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                # Validate that LLM response doesn't contain the nonce
                if nonce in llm_answer:
                    log.error("LLM response contains nonce value, rejecting response")
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                for match_prefix in ["##", "**"]:
                    markdown_parser = MarkdownFlatParser(llm_answer, section_marker_prefix=match_prefix)
                    log.debug("Obtained sections from LLM: %r", markdown_parser.get_all_sections())
                    patched_function = markdown_parser.get_markdown_section(ADAPTED_SNIPPET_HEADER)
                    if patched_function:
                        break

                if not patched_function:
                    log.warning(
                        "LLM answer does not contain expected section '%s', falling back to patching hunk-by-hunk",
                        ADAPTED_SNIPPET_HEADER,
                    )
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                # Validate extracted patched function section
                if not validate_extracted_llm_content(patched_function, "code"):
                    log.warning("LLM patched function contains invalid content, falling back to patching hunk-by-hunk")
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                patched_function_lines = patched_function.splitlines()
                try:
                    patched_function_start, patched_function_end, patched_function_lines = code_section_location(
                        section_header, patched_function_lines
                    )
                except RuntimeError:
                    log.warning("Failed to retrieve function definition for %s in adapted code", section_header)
                    for hunk in nonempty_hunk_section_map[section_header]:
                        hunks_with_empty_section.append(hunk)
                    continue

                log.debug(
                    "Patched function lines:\n%s",
                    "\n".join(patched_function_lines[patched_function_start - 1 : patched_function_end]),
                )

                if self.llm_limits.any_post():
                    function_local_dst_lines = dst_source_file_lines[
                        context_dst_function_start:context_dst_function_end
                    ]
                    src_section_start, src_section_end, src_section_lines = code_section_location(
                        section_header, function_local_dst_lines
                    )
                    llm_generated_hunk = list(
                        difflib.unified_diff(
                            src_section_lines[src_section_start - 1 : src_section_end - 1],
                            patched_function_lines[patched_function_start - 1 : patched_function_end - 1],
                        )
                    )
                    if (
                        len(llm_generated_hunk) > 2
                        and llm_generated_hunk[0].startswith("---")
                        and llm_generated_hunk[1].startswith("+++")
                    ):
                        llm_generated_hunk = llm_generated_hunk[2:]
                    if not validate_llm_output(
                        self.llm_limits,
                        rejected_hunk_content.splitlines(),
                        llm_generated_hunk,
                    ):
                        return False, "Proposed LLM change was rejected by interactive user", None
                    else:
                        log.debug("LLM output passed validation for section")

                # Create new file lines from 0 to src_function_start, then add lines from patch_function_lines, then add remaining lines after src_function_end
                new_file_lines = (
                    dst_source_file_lines[0 : dst_function_start - 1]
                    + patched_function_lines[patched_function_start - 1 : patched_function_end]
                    + dst_source_file_lines[dst_function_end:]
                )
                dst_source_file_lines = new_file_lines

                llm_explanation = markdown_parser.get_markdown_section(SUMMARY_SECTION_HEADER)
                if not llm_explanation:
                    llm_explanation = (
                        f"LLM generated fix for hunk {section_header} -- failed to extract change summary from LLM"
                    )

                # Validate extracted explanation section
                if not validate_extracted_llm_content(llm_explanation, "explanation"):
                    return False, "LLM explanation section contains invalid content", None

                log.debug("To be added in case commit is picked: %s", llm_explanation)
                modification_explanations.append(llm_explanation)

            log.debug("Writing modified version of file %s", rejected_patch.target_file())
            with open(rejected_patch.target_file(), "w", encoding="utf-8") as outfile:
                outfile.write("\n".join(dst_source_file_lines))
                if last_line_newline:
                    outfile.write("\n")

            if hunks_with_empty_section:
                log.info(
                    "Processing %d hunks with empty section or that failed on full section ...",
                    len(hunks_with_empty_section),
                )
                success, error_text, apply_messages = self.apply_hunks_with_empty_section(
                    hunks_with_empty_section, rejected_patch.target_file(), commit_message
                )
                if not success:
                    log.error(
                        "Failed to apply hunks with empty section for file %s with error %s",
                        rejected_patch.target_file(),
                        error_text,
                    )
                    return False, error_text, None
                modification_explanations.extend(apply_messages)

            # If all hunks have been processed without error, we modified the file and have no rejected file anymore
            rejected_patch.remove_file()

        log.info("Stats from LLM interaction: %r", self.llm_client().get_stats())

        return (
            True,
            None,
            f"LLM-adjusted hunks for {len(modification_explanations)} functions from {self.llm_client().get_model_prefix()}"
            + "\n"
            + "\n".join(modification_explanations),
        )
