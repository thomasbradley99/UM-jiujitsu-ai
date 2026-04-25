"""Gemini response schema for submission detection.

Kept separate so it can be imported by detect.py without pulling in the rest
of the pipeline. Uses google-genai's `Type` enum.
"""

from google.genai import types as genai_types


SUB_TYPES = [
    "armbar",
    "kimura",
    "americana",
    "triangle",
    "rear_naked_choke",
    "guillotine",
    "omoplata",
    "ankle_lock",
    "knee_bar",
    "heel_hook",
    "ezekiel",
    "bow_and_arrow",
    "north_south_choke",
    "gogoplata",
    "unknown",
]


def submission_response_schema() -> genai_types.Schema:
    """Return the JSON schema enforced on Gemini's response.

    Output shape: array of submission events, each with timestamp / sub_type /
    attacker / defender / outcome / confidence.
    """
    return genai_types.Schema(
        type=genai_types.Type.ARRAY,
        items=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={
                "timestamp": genai_types.Schema(
                    type=genai_types.Type.NUMBER,
                    description="Seconds from the start of the video.",
                ),
                "sub_type": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    enum=SUB_TYPES,
                    description="Canonical submission name from the allowed list.",
                ),
                "attacker": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    enum=["fighter1", "fighter2"],
                ),
                "defender": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    enum=["fighter1", "fighter2"],
                ),
                "outcome": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    enum=["successful", "escaped", "ongoing"],
                ),
                "confidence": genai_types.Schema(
                    type=genai_types.Type.NUMBER,
                    description="0.0 - 1.0",
                ),
            },
            required=["timestamp", "sub_type", "attacker", "defender", "outcome", "confidence"],
        ),
    )
