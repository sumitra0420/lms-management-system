"""
Lets run_integration_test.py A/B test the "CRITICAL — do not truncate..."
ASSESSOR KEY paragraph added in commit b982274, without editing extractor.py
or checking out git history.

variant "new" -> current app/services/extractor.py SYSTEM_PROMPT, unchanged.
variant "old" -> the same SYSTEM_PROMPT with only that one paragraph removed,
                 so the comparison isolates the effect of that paragraph
                 rather than reverting later, unrelated prompt fixes
                 (e.g. the MCQ/"All of the above" rules added in c80cd2e).

Run from inside backend/:
    python tests/run_integration_test.py tests/input/Quiz integration/result_claude_nova_oldprompt_270726 old
    python tests/run_integration_test.py tests/input/Quiz integration/result_claude_nova_newprompt_270726 new
"""

import re

from app.services.extractor import SYSTEM_PROMPT as CURRENT_SYSTEM_PROMPT

_ABLATION_PATTERN = re.compile(
    r"\n\s*CRITICAL — do not truncate.*?the number mentioned in the question\.\n",
    re.DOTALL,
)

ABLATED_SYSTEM_PROMPT, _MATCH_COUNT = _ABLATION_PATTERN.subn("\n", CURRENT_SYSTEM_PROMPT)


def get_prompt(variant: str) -> str:
    if variant == "new":
        return CURRENT_SYSTEM_PROMPT
    if variant == "old":
        if _MATCH_COUNT != 1:
            raise RuntimeError(
                f"Expected exactly 1 CRITICAL-paragraph match to ablate, found {_MATCH_COUNT}. "
                "extractor.py's SYSTEM_PROMPT wording has likely changed since this ablation "
                "regex was written — update _ABLATION_PATTERN in prompt_variants.py."
            )
        return ABLATED_SYSTEM_PROMPT
    raise ValueError(f"Unknown prompt variant: {variant!r} (expected 'old' or 'new')")
