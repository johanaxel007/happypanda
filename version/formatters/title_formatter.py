# Based on https://github.com/x94fujo6rpg/SomeTampermonkeyScripts/raw/master/dlsite_title_reformat.user.js

import logging
import re
from enum import StrEnum

import unicodedata

log = logging.getLogger(__name__)


# --- Enums ---
class TranslationStyle(StrEnum):
    """Enum for selecting the forbidden character translation style."""
    DEFAULT = 'default'
    GALLERY_INFO_COPY = 'gallery_info_copy'
    SEARCH = 'search'


# --- Constants ---
# Container definitions
CONTAINER_LIST: list[str] = ['()', '[]', '{}', '（）', '<>', '［］', '｛｝', '【】', '『』', '《》', '〈〉', '「」']
# Pre-calculate start and end characters for faster lookups
_container_tuples: list[tuple[str, str]] = [(c[0], c[1]) for c in CONTAINER_LIST]
CONTAINER_START: str = ''.join(t[0] for t in _container_tuples)
CONTAINER_END: str = ''.join(t[1] for t in _container_tuples)

# Forbidden character replacement map (Default)
FORBIDDEN_CHARS: str = '<>:""/|?*\\'
REPLACER_CHARS: str = '＜＞：”＂／｜？＊＼'
FORBIDDEN_TRANSLATION: dict = str.maketrans(FORBIDDEN_CHARS, REPLACER_CHARS)

# Gallery Info Copy style replacement map
# Matches behavior of x/gallery-info-copy userscript
# Replaces: < > : " / \ | ? * and control chars (0x00-0x1F)
_GALLERY_INFO_COPY_MAP: dict[str, str] = {
    '<': '\uFF1C',  # ＜
    '>': '\uFF1E',  # ＞
    ':': '\uFF1A',  # ：
    '"': '\uFF02',  # ＂
    '/': '\uFF0F',  # ／
    '\\': '\uFF0F',  # ／ (Backslash maps to Slash in this style)
    '|': '\uFF5C',  # ｜
    '?': '\uFF1F',  # ？
    '*': '\uFF0A',  # ＊
}
# Map control characters 0x00-0x1F to '-'
for _i in range(32):
    _GALLERY_INFO_COPY_MAP[chr(_i)] = '-'

GALLERY_INFO_COPY_TRANSLATION: dict = str.maketrans(_GALLERY_INFO_COPY_MAP)

# Search style replacement map
# The inverse of FORBIDDEN_TRANSLATION: folds the full-width stand-ins a filesystem forces onto
# a title back to ASCII, most importantly '｜' -> '|', the separator sources actually index.
SEARCH_TRANSLATION: dict = str.maketrans(REPLACER_CHARS, FORBIDDEN_CHARS)

# Full-width to half-width conversion map
DEFAULT_FULL: str = '１２３４５６７８９０（）［］｛｝～！＠＃＄％︿＆＿＋－＝；’：，．（）〜'
DEFAULT_HALF: str = "1234567890()[]{}~!@#$%^&_+-=;':,.()~"
FULL_TO_HALF_TRANSLATION: dict = str.maketrans(DEFAULT_FULL, DEFAULT_HALF)

# Full-width to half-width conversion map, including normally forbidden characters
DEFAULT_FULL_FORBIDDEN: str = DEFAULT_FULL + REPLACER_CHARS
DEFAULT_HALF_FORBIDDEN: str = DEFAULT_HALF + FORBIDDEN_CHARS
FULL_TO_HALF_FORBIDDEN_TRANSLATION: dict = str.maketrans(DEFAULT_FULL_FORBIDDEN, DEFAULT_HALF_FORBIDDEN)


# --- Compiled Regular Expressions ---
def _build_container_regex_part(containers: list[tuple[str, str]], all_starts: str, all_ends: str) -> str:
    """Builds the regex part matching any single container pair."""
    # Escape all possible start/end characters *once* for the exclusion class
    escaped_brackets = re.escape(all_starts + all_ends)
    parts: list[str] = []
    for start, end in containers:
        # Match start, then non-brackets, then end
        parts.append(f'{re.escape(start)}[^{escaped_brackets}]*{re.escape(end)}')
    return f'({"|".join(parts)})'  # Group the alternatives


# Regex part matching any single container (e.g., 【text】, (text))
_CONTAINER_REGEX_PART: str = _build_container_regex_part(_container_tuples, CONTAINER_START, CONTAINER_END)

# Regex to remove leading/trailing container structures (with surrounding whitespace)
REG_EXCESS = re.compile(rf'^\s*{_CONTAINER_REGEX_PART}\s*|\s*{_CONTAINER_REGEX_PART}\s*$', re.UNICODE)

# Regex for multiple whitespace characters
REG_BLANK = re.compile(r'\s{2,}', re.UNICODE)


# --- Helper Functions ---
def remove_excess(text: str) -> str:
    """Removes specific leading/trailing bracketed content and redundant whitespace.

    :param text: The string to process.
    :returns: The processed string.
    """
    if not isinstance(text, str) or not text:
        return text

    original_text: str = text
    processed_text: str = text.strip()  # Initial trim

    # --- First pass: Remove leading/trailing container structures using regex ---
    # Loop necessary to remove nested/layered containers at ends, e.g. "【 (Text) 】"
    MAX_ITERATIONS = 100  # Safety break  # noqa: N806
    for _ in range(MAX_ITERATIONS):
        new_text = REG_EXCESS.sub('', processed_text).strip()
        if new_text == processed_text:  # No change, layer removal finished
            break
        processed_text = new_text
    else:  # Safety break hit
        # Log or handle the case where max iterations were reached, if necessary
        log.warning(f"Warning: Max iterations reached during regex excess removal for: '{original_text}'")

    # --- Second pass: Manual single bracket stripping at edges ---
    # Handles cases like "[Unmatched" or "Unmatched]" or removes matched pairs
    # missed by regex (if regex was imperfect) or created by prior steps.
    for _ in range(MAX_ITERATIONS):
        if len(processed_text) <= 1:  # Can't be a pair or have content
            break

        start_char = processed_text[0]
        end_char = processed_text[-1]
        changed_this_iteration = False

        # Check start character
        try:
            start_index = CONTAINER_START.index(start_char)  # Efficient lookup
            corresponding_end = CONTAINER_END[start_index]
            if end_char == corresponding_end:
                # Found matching pair: remove both
                processed_text = processed_text[1:-1].strip()
                changed_this_iteration = True
            elif corresponding_end not in processed_text[1:]:
                # Found start, but no corresponding end exists later: remove start only
                processed_text = processed_text[1:].strip()
                changed_this_iteration = True
        except ValueError:
            # Start char is not a known container start
            pass

        # Check end character *only if* start char logic didn't change the string
        if not changed_this_iteration and len(processed_text) > 1:  # Re-check length
            try:
                end_index = CONTAINER_END.index(end_char)
                corresponding_start = CONTAINER_START[end_index]
                # Found end, but no corresponding start exists earlier: remove end only
                if corresponding_start not in processed_text[:-1]:
                    processed_text = processed_text[:-1].strip()
                    changed_this_iteration = True
            except ValueError:
                # End char is not a known container end
                pass

        # If no changes were made in this iteration, the string is stable
        if not changed_this_iteration:
            break
    else:  # Safety break hit
        log.warning(f"Warning: Max iterations reached during manual bracket stripping for: '{original_text}'")

    # --- Final cleanup ---
    # Replace multiple spaces (including full-width) with a single space
    processed_text = REG_BLANK.sub(' ', processed_text).strip()

    # Return original if processing resulted in empty string
    return processed_text if processed_text else original_text


def to_half_width(text: str) -> str:
    """
    Converts specific full-width characters to half-width using the script's map.

    Args:
        text: The string to process.

    Returns:
        The processed string with specific characters converted to half-width.
    """
    if not isinstance(text, str):
        return text  # pyright: ignore [reportUnreachable]
    return text.translate(FULL_TO_HALF_TRANSLATION)


def to_half_width_including_forbidden(text: str) -> str:
    """
    Converts specific full-width characters to half-width using the script's map.
    This version includes characters that are normally forbidden in filenames.

    Args:
        text: The string to process.

    Returns:
        The processed string with specific characters converted to half-width.
    """
    if not isinstance(text, str):
        return text  # pyright: ignore [reportUnreachable]
    return text.translate(FULL_TO_HALF_FORBIDDEN_TRANSLATION)


def replace_forbidden_chars(text: str) -> str:
    """
    Replaces characters forbidden in filenames with their full-width equivalents.
    Uses the default translation map.

    Args:
        text: The string to process.

    Returns:
        The processed string with forbidden characters replaced.
    """
    if not isinstance(text, str):
        return text  # pyright: ignore [reportUnreachable]
    return text.translate(FORBIDDEN_TRANSLATION)


# --- Main Formatting Function ---
def format_title(
        text: str,
        *,
        convert_to_half_width_flag: bool = True,
        use_python_normalization: bool = False,
        translation_style: TranslationStyle = TranslationStyle.DEFAULT,
) -> str:
    """
    Cleans and reformats a title string based on the logic from the UserScript.

    Args:
        text: The original title string.
        convert_to_half_width_flag: If True, perform full-width to half-width conversion.
        use_python_normalization: If True and convert_to_half_width_flag is True,
                                   uses Python's standard unicodedata.normalize('NFKC')
                                   for a broader conversion, overriding the script's
                                   specific mapping.
        translation_style: The style of forbidden character replacement.
                           Uses TranslationStyle enum.

    Returns:
        The formatted title string.
    """
    if not isinstance(text, str):
        # Consider raising TypeError for invalid input
        return text  # pyright: ignore [reportUnreachable]

    formatted_text = remove_excess(text)

    if convert_to_half_width_flag:
        if use_python_normalization:
            # Broader conversion using Python standard library
            formatted_text = unicodedata.normalize('NFKC', formatted_text)
        elif formatted_text:  # Only translate if not empty
            # Specific conversion mimicking the script's table
            formatted_text = formatted_text.translate(FULL_TO_HALF_TRANSLATION)

    if formatted_text:  # Only translate if not empty
        if translation_style == TranslationStyle.GALLERY_INFO_COPY:
            formatted_text = formatted_text.translate(GALLERY_INFO_COPY_TRANSLATION)
        elif translation_style == TranslationStyle.SEARCH:
            formatted_text = formatted_text.translate(SEARCH_TRANSLATION)
        else:
            formatted_text = formatted_text.translate(FORBIDDEN_TRANSLATION)

    return formatted_text
