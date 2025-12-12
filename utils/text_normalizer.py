"""
Text normalization utilities for handling spacing variations.
"""

from typing import List
import re


def normalize_spacing(text: str) -> str:
    """
    Remove all spaces from text for consistent matching.

    Args:
        text: Input text

    Returns:
        Text with spaces removed

    Example:
        "픽코 파트너스" -> "픽코파트너스"
        "픽 코 파 트 너 스" -> "픽코파트너스"
    """
    return text.replace(' ', '')


def generate_spacing_variants(keyword: str) -> List[str]:
    """
    Generate spacing variations for a keyword.

    Args:
        keyword: Original keyword

    Returns:
        List of spacing variants

    Example:
        "픽코파트너스" -> ["픽코파트너스", "픽코 파트너스", "픽 코 파 트 너 스"]
        "픽코 파트너스" -> ["픽코파트너스", "픽코 파트너스"]
    """
    variants = []

    # Original
    variants.append(keyword)

    # No spaces
    no_space = normalize_spacing(keyword)
    if no_space != keyword:
        variants.append(no_space)

    # If already has spaces, that's the "with space" version
    # If no spaces, try to add common spacing patterns
    if ' ' not in keyword and len(keyword) >= 4:
        # Try splitting at common points (every 2-3 characters)
        # This is heuristic for Korean words
        if len(keyword) >= 4:
            mid = len(keyword) // 2
            spaced = keyword[:mid] + ' ' + keyword[mid:]
            variants.append(spaced)

    # Remove duplicates while preserving order
    seen = set()
    result = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            result.append(v)

    return result


def create_flexible_search_pattern(keyword: str) -> str:
    """
    Create a regex pattern that matches regardless of spacing.

    Args:
        keyword: Search keyword

    Returns:
        Regex pattern string

    Example:
        "픽코파트너스" -> "픽\s*코\s*파\s*트\s*너\s*스"
    """
    # Remove existing spaces
    no_space = normalize_spacing(keyword)

    # Insert \s* between each character to allow optional spaces
    chars = list(no_space)
    pattern = r'\s*'.join(re.escape(char) for char in chars)

    return pattern


def normalize_for_comparison(text: str) -> str:
    """
    Normalize text for comparison (lowercase + no spaces).

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    # Remove spaces
    text = normalize_spacing(text)

    # Lowercase (for mixed Korean-English)
    text = text.lower()

    return text


def fuzzy_contains(haystack: str, needle: str) -> bool:
    """
    Check if needle is contained in haystack, ignoring spacing.

    Args:
        haystack: Text to search in
        needle: Text to search for

    Returns:
        True if needle is found (ignoring spaces)

    Example:
        fuzzy_contains("픽코 파트너스 회사", "픽코파트너스") -> True
        fuzzy_contains("픽코파트너스 회사", "픽코 파트너스") -> True
    """
    normalized_haystack = normalize_for_comparison(haystack)
    normalized_needle = normalize_for_comparison(needle)

    return normalized_needle in normalized_haystack
