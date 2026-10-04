"""Small, reviewable emergency override; policy data can expand in later waves."""

import re
from dataclasses import dataclass


POLICY_VERSION = "ng-emergency-2026-09-24"


@dataclass(frozen=True)
class SafetyEvaluation:
    urgent_override: bool
    flags: tuple[str, ...]
    policy_version: str = POLICY_VERSION


def evaluate_safety(message: str) -> SafetyEvaluation:
    text = " ".join(message.lower().split())
    personal = bool(re.search(r"\b(i|i'm|i've|my|me|we|our|he|she|they|someone)\b", text))
    informational = bool(re.match(r"^(what|why|how|can|could|does|is|are|explain|tell me about)\b", text))
    current_report = bool(re.search(
        r"\b(i have|i'm having|i am having|i can't|i cannot|my .{0,30} is|"
        r"he is|she is|someone is|they are)\b", text
    ))
    if not personal or (informational and not current_report):
        return SafetyEvaluation(False, ())

    flags = []
    severe_chest_pain = re.search(r"\b(severe|crushing|intense) chest pain\b", text)
    breathing_crisis = re.search(
        r"\b(can't breathe|cannot breathe|severe difficulty breathing|struggling to breathe)\b", text
    )
    if severe_chest_pain and re.search(
        r"\b(can't breathe|cannot breathe|difficulty breathing|shortness of breath|struggling to breathe)\b", text
    ):
        flags.append("chest_pain_breathlessness")
    elif severe_chest_pain or breathing_crisis:
        flags.append("severe_chest_pain_or_breathing_crisis")
    if re.search(r'\bchest pain\b', text) and re.search(
        r'\b(sweating|cold sweat|dizziness|shortness of breath|nausea)\b', text
    ):
        flags.append('chest_pain_warning_signs')
    if re.search(r'\b(suddenly|sudden) short of breath\b', text):
        flags.append('sudden_breathlessness')
    if re.search(r'\b(sudden|suddenly) severe headache\b', text):
        flags.append('sudden_severe_headache')
    if re.search(r'\b(pregnant|pregnancy)\b', text) and re.search(
        r'\bsevere headache\b', text
    ) and re.search(r'\b(swelling|vision changes|blurred vision)\b', text):
        flags.append('pregnancy_warning_signs')
    if re.search(r'\bdiabetes\b', text) and re.search(r'\bconfused\b', text):
        flags.append('diabetes_confusion')
    if re.search(r'\b(child|infant|baby)\b', text) and re.search(
        r'\bfever\b', text
    ) and re.search(r'\b(unusually sleepy|hard to wake|confused)\b', text):
        flags.append('child_fever_alertness')
    if re.search(r'\b(harm myself|kill myself|end my life)\b', text) and re.search(
        r'\b(may|might|will|going to|tonight|now|unsafe)\b', text
    ):
        flags.append('imminent_self_harm')
    if re.search(r"\b(bleeding heavily|severe bleeding|uncontrolled bleeding|won't stop bleeding)\b", text):
        flags.append("severe_bleeding")
    if re.search(r"\b(unconscious|unresponsive|not breathing)\b", text):
        flags.append("unconscious_or_not_breathing")
    if re.search(r"\b(sudden|suddenly)\b", text) and re.search(
        r"\b(face droop|facial droop|one.side(d)? weakness|slurred speech|can't speak)\b", text
    ):
        flags.append("stroke_signs")
    return SafetyEvaluation(bool(flags), tuple(flags))
