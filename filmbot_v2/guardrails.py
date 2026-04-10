"""
FilmBot V2 — Guardrails Module

Implements 7 guardrail categories:
  1. Data/Content Accuracy — responses grounded in database, not hallucinated
  2. Role-Based Restrictions — user roles control access level
  3. Data Access & Compliance — block irrelevant/out-of-scope queries
  4. Ethical & Compliance — block biased, offensive, or harmful content
  5. Real-Time Monitoring — log all interactions with timestamps
  6. Security & Privacy — block PII extraction, SQL injection, prompt injection
  7. Customizable Guardrails — configurable blocked topics and keywords
"""

import re
import json
import time
import logging
from datetime import datetime
from dataclasses import dataclass, field

# ── Logging setup (Real-Time Monitoring) ──────────────────────

logging.basicConfig(
    filename="filmbot_interactions.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("filmbot_guardrails")


# ── Configuration ─────────────────────────────────────────────

@dataclass
class GuardrailConfig:
    """Customizable guardrail settings."""

    # Allowed topics (Data Access & Compliance)
    allowed_domain: str = "IMDB movies database"
    allowed_topics: list = field(default_factory=lambda: [
        "movies", "films", "actors", "actresses", "directors", "ratings",
        "genres", "box office", "gross", "imdb", "cinema", "plot",
        "cast", "star", "review", "score", "year", "release",
        "runtime", "certificate", "votes", "meta score", "overview",
        "thriller", "drama", "action", "comedy", "horror", "sci-fi",
        "romance", "animation", "adventure", "crime", "fantasy",
        "biography", "history", "war", "western", "musical", "mystery",
        "recommendations", "suggest", "similar", "like",
    ])

    # Blocked patterns (Security & Privacy)
    sql_injection_patterns: list = field(default_factory=lambda: [
        r"DROP\s+TABLE", r"DELETE\s+FROM", r"UPDATE\s+.*SET",
        r"INSERT\s+INTO", r"ALTER\s+TABLE", r"CREATE\s+TABLE",
        r"UNION\s+SELECT", r"--\s*$", r"EXEC\s+",
        r"TRUNCATE\s+TABLE", r";\s*SELECT\s+",
    ])

    pii_patterns: list = field(default_factory=lambda: [
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",          # phone numbers
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # emails
        r"\b\d{3}-\d{2}-\d{4}\b",                    # SSN
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # credit cards
        r"\b(?:password|passwd|pwd)\s*[:=]\s*\S+",    # passwords
    ])

    # Blocked content (Ethical & Compliance)
    offensive_keywords: list = field(default_factory=lambda: [
        "hate speech", "racial slur", "discriminat",
        "sexist", "homophobic", "violent threat",
        "self-harm", "suicide method", "how to kill",
        "illegal drug", "how to hack", "exploit vulnerability",
    ])

    # Prompt injection patterns (Security)
    prompt_injection_patterns: list = field(default_factory=lambda: [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?above",
        r"you\s+are\s+now\s+(?:a|an)\s+(?!movie|film)",
        r"act\s+as\s+(?!a\s+movie|filmbot)",
        r"system\s*prompt",
        r"reveal\s+(your|the)\s+(instructions|prompt|system)",
        r"forget\s+(everything|all|your\s+rules)",
    ])

    # Role-based access levels
    roles: dict = field(default_factory=lambda: {
        "user": {
            "can_query": True,
            "can_batch_query": False,
            "can_clear_cache": False,
            "max_queries_per_min": 10,
        },
        "admin": {
            "can_query": True,
            "can_batch_query": True,
            "can_clear_cache": True,
            "max_queries_per_min": 100,
        },
    })


# ── Guardrail Result ──────────────────────────────────────────

@dataclass
class GuardrailResult:
    passed: bool
    category: str = ""
    message: str = ""
    flagged_content: str = ""


# ── Guardrail Engine ──────────────────────────────────────────

class GuardrailEngine:
    def __init__(self, config: GuardrailConfig = None):
        self.config = config or GuardrailConfig()
        self._query_timestamps: dict[str, list[float]] = {}

    def check_input(self, question: str, user_role: str = "user") -> GuardrailResult:
        """Run all input guardrails. Returns first failure or a pass."""

        checks = [
            self._check_security(question),
            self._check_ethical(question),
            self._check_scope(question),
            self._check_role_access(user_role, "can_query"),
            self._check_rate_limit(user_role),
        ]

        for result in checks:
            if not result.passed:
                self._log_blocked(question, result)
                return result

        self._log_allowed(question, user_role)
        return GuardrailResult(passed=True, category="all", message="All guardrails passed")

    def check_output(self, question: str, response: str, tools_used: list[str]) -> GuardrailResult:
        """Run output guardrails to ensure response quality."""

        # 1. Data/Content Accuracy — ensure response is grounded (tool-based)
        accuracy_check = self._check_data_accuracy(response, tools_used)
        if not accuracy_check.passed:
            return accuracy_check

        # 2. Ethical check on output
        ethical_check = self._check_ethical(response)
        if not ethical_check.passed:
            return GuardrailResult(
                passed=False,
                category="ethical_output",
                message="Response flagged for potentially inappropriate content. Regenerating...",
                flagged_content=ethical_check.flagged_content,
            )

        # 3. Check for PII leakage in response
        pii_check = self._check_pii_in_response(response)
        if not pii_check.passed:
            return pii_check

        return GuardrailResult(passed=True, category="output", message="Output guardrails passed")

    # ── Individual checks ─────────────────────────────────────

    def _check_security(self, text: str) -> GuardrailResult:
        """Security & Privacy — block SQL injection, prompt injection, PII extraction."""
        text_lower = text.lower()

        # SQL injection
        for pattern in self.config.sql_injection_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return GuardrailResult(
                    passed=False,
                    category="security",
                    message="Potentially unsafe SQL pattern detected. Please rephrase your question.",
                    flagged_content=pattern,
                )

        # Prompt injection
        for pattern in self.config.prompt_injection_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return GuardrailResult(
                    passed=False,
                    category="security",
                    message="I can only help with movie-related questions. Let's talk about films!",
                    flagged_content=pattern,
                )

        # PII in input
        for pattern in self.config.pii_patterns:
            if re.search(pattern, text):
                return GuardrailResult(
                    passed=False,
                    category="security",
                    message="Please don't include personal information in your queries. I only need movie-related questions!",
                    flagged_content="PII detected",
                )

        return GuardrailResult(passed=True)

    def _check_ethical(self, text: str) -> GuardrailResult:
        """Ethical & Compliance — block biased, offensive, or harmful content."""
        text_lower = text.lower()

        for keyword in self.config.offensive_keywords:
            if keyword.lower() in text_lower:
                return GuardrailResult(
                    passed=False,
                    category="ethical",
                    message="I'm here to help with movies! Let's keep the conversation film-focused.",
                    flagged_content=keyword,
                )

        return GuardrailResult(passed=True)

    def _check_scope(self, question: str) -> GuardrailResult:
        """Data Access & Compliance — filter out-of-scope queries."""
        q_lower = question.lower().strip()

        # Allow greetings
        greetings = ["hi", "hello", "hey", "good morning", "good evening",
                     "good afternoon", "thanks", "thank you", "bye", "goodbye"]
        if q_lower in greetings or any(q_lower.startswith(g) for g in greetings):
            return GuardrailResult(passed=True)

        # Check if question relates to allowed topics
        has_movie_context = any(topic in q_lower for topic in self.config.allowed_topics)

        if not has_movie_context:
            # Check for common off-topic patterns
            off_topic_patterns = [
                r"what\s+is\s+the\s+(?:capital|president|population|weather)",
                r"how\s+to\s+(?:cook|code|build|fix|make)(?!\s+a\s+(?:movie|film))",
                r"(?:solve|calculate|compute)\s+\d",
                r"write\s+(?:a\s+)?(?:code|program|script|essay|poem|python|java|function)",
                r"(?:explain|what\s+is)\s+(?:quantum|photosynthesis|gravity|blockchain|crypto)",
                r"(?:news|stock|weather|sports score)",
            ]
            for pattern in off_topic_patterns:
                if re.search(pattern, q_lower):
                    return GuardrailResult(
                        passed=False,
                        category="scope",
                        message=f"I'm FilmBot — your movie expert! I can only answer questions about the {self.config.allowed_domain}. "
                                f"Try asking about movies, actors, directors, ratings, or genres!",
                    )

        return GuardrailResult(passed=True)

    def _check_role_access(self, role: str, permission: str) -> GuardrailResult:
        """Role-Based Restrictions — check user permissions."""
        role_config = self.config.roles.get(role, self.config.roles["user"])

        if not role_config.get(permission, False):
            return GuardrailResult(
                passed=False,
                category="role",
                message=f"Your role '{role}' doesn't have permission for this action.",
            )

        return GuardrailResult(passed=True)

    def _check_rate_limit(self, user_role: str) -> GuardrailResult:
        """Rate limiting per role."""
        role_config = self.config.roles.get(user_role, self.config.roles["user"])
        max_qpm = role_config.get("max_queries_per_min", 10)

        now = time.time()
        timestamps = self._query_timestamps.get(user_role, [])
        # Keep only last 60 seconds
        timestamps = [t for t in timestamps if now - t < 60]
        self._query_timestamps[user_role] = timestamps

        if len(timestamps) >= max_qpm:
            return GuardrailResult(
                passed=False,
                category="rate_limit",
                message=f"Rate limit exceeded ({max_qpm} queries/min). Please wait a moment.",
            )

        timestamps.append(now)
        return GuardrailResult(passed=True)

    def _check_data_accuracy(self, response: str, tools_used: list[str]) -> GuardrailResult:
        """Data/Content Accuracy — ensure response is grounded in tool results."""
        # If tools were used, the response is grounded in database data
        if tools_used:
            return GuardrailResult(passed=True)

        # If no tools used but it's a data question, flag it
        data_indicators = ["top", "best", "worst", "how many", "count", "average",
                           "highest", "lowest", "most", "least", "rating", "gross"]
        resp_lower = response.lower()

        if any(indicator in resp_lower for indicator in data_indicators):
            return GuardrailResult(
                passed=False,
                category="accuracy",
                message="I should verify this with the database. Let me look that up for you.",
            )

        return GuardrailResult(passed=True)

    def _check_pii_in_response(self, response: str) -> GuardrailResult:
        """Check for accidental PII leakage in response."""
        for pattern in self.config.pii_patterns:
            if re.search(pattern, response):
                return GuardrailResult(
                    passed=False,
                    category="privacy",
                    message="Response contained potentially sensitive information and was filtered.",
                    flagged_content="PII in output",
                )
        return GuardrailResult(passed=True)

    # ── Logging (Real-Time Monitoring) ────────────────────────

    def _log_blocked(self, question: str, result: GuardrailResult):
        logger.warning(
            f"BLOCKED | category={result.category} | "
            f"question={question[:100]} | reason={result.message}"
        )

    def _log_allowed(self, question: str, role: str):
        logger.info(f"ALLOWED | role={role} | question={question[:100]}")

    def log_interaction(self, question: str, response: str, tools_used: list[str],
                        latency: float, role: str = "user"):
        """Log complete interaction for monitoring."""
        logger.info(
            f"INTERACTION | role={role} | latency={latency}s | "
            f"tools={','.join(tools_used)} | "
            f"question={question[:100]} | response_len={len(response)}"
        )
