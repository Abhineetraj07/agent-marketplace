"""
Input/Output sanitization for the marketplace.
Blocks SQL injection, prompt injection, PII leakage, path traversal.
"""

import re
import unicodedata

MAX_INPUT_LENGTH = 1000  # Max characters per question


def _normalize_text(text: str) -> str:
    """Normalize unicode to defeat homoglyph and invisible-char attacks.
    NFKC maps full-width, Cyrillic lookalikes, etc. to ASCII equivalents.
    Then strips zero-width and control characters.
    """
    # NFKC normalization: full-width → ASCII, compatibility decomposition
    normalized = unicodedata.normalize("NFKC", text)
    # Remove zero-width spaces, joiners, soft hyphens, and other invisible chars
    normalized = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u180e]", "", normalized)
    # Remove HTML entities like &#83;
    normalized = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), normalized)
    normalized = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), normalized)
    # Map Cyrillic/Greek lookalikes to ASCII equivalents
    _HOMOGLYPH_MAP = str.maketrans({
        "\u0410": "A", "\u0430": "a",  # Cyrillic А/а
        "\u0412": "B", "\u0432": "b",  # Cyrillic В/в (looks like B)
        "\u0421": "C", "\u0441": "c",  # Cyrillic С/с
        "\u0415": "E", "\u0435": "e",  # Cyrillic Е/е
        "\u041d": "H", "\u043d": "h",  # Cyrillic Н/н
        "\u041a": "K", "\u043a": "k",  # Cyrillic К/к
        "\u041c": "M", "\u043c": "m",  # Cyrillic М/м
        "\u041e": "O", "\u043e": "o",  # Cyrillic О/о
        "\u0420": "P", "\u0440": "p",  # Cyrillic Р/р
        "\u0405": "S", "\u0455": "s",  # Cyrillic Ѕ/ѕ
        "\u0422": "T", "\u0442": "t",  # Cyrillic Т/т
        "\u0425": "X", "\u0445": "x",  # Cyrillic Х/х
        "\u0423": "Y", "\u0443": "y",  # Cyrillic У/у
    })
    normalized = normalized.translate(_HOMOGLYPH_MAP)
    return normalized


def _deobfuscate_text(text: str) -> str:
    """Collapse D.I.S.R.E.G.A.R.D / I g n o r e style obfuscation."""
    # Strip dots between single letters: D.I.S.R.E.G.A.R.D → DISREGARD
    collapsed = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", "", text)
    # Strip single spaces between single letters: I g n o r e → Ignore
    collapsed = re.sub(r"(?<=[A-Za-z]) (?=[A-Za-z](?:\b| ))", "", collapsed)
    return collapsed

# ── SQL Injection Patterns ───────────────────────────────────

SQL_INJECTION_PATTERNS = [
    r"DROP\s+TABLE",
    r"DELETE\s+FROM",
    r"UPDATE\s+.*SET",
    r"INSERT\s+INTO",
    r"ALTER\s+TABLE",
    r"CREATE\s+TABLE",
    r"UNION\s+(ALL\s+)?SELECT",
    r"--\s*$",
    r"EXEC\s+",
    r"TRUNCATE\s+TABLE",
    r";\s*SELECT\s+",
    r"'\s*OR\s+'1'\s*=\s*'1",
    r"'\s*OR\s+1\s*=\s*1",
    r";\s*DROP\s+",
    r"INFORMATION_SCHEMA",
    r"xp_cmdshell",
    # New: patterns the pentest bypassed
    r"SELECT\s+.*FROM\s+\w+",             # any SELECT...FROM
    r"PRAGMA\s+",                          # SQLite PRAGMA commands
    r"sqlite_master",                      # SQLite system table
    r"\.tables",                           # SQLite dot-commands
    r"\.schema",
    r"\.dump",
    r"ATTACH\s+DATABASE",                  # SQLite attach
    r"LOAD_EXTENSION",                     # SQLite extension loading
    r"password_hash",                      # direct column reference
    r"api_key\s+FROM",                     # direct key extraction
]

# ── Prompt Injection Patterns ────────────────────────────────

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above",
    r"forget\s+(everything|all|your\s+rules)",
    r"system\s*prompt",
    r"reveal\s+(your|the)\s+(instructions|prompt|system)",
    r"print\s+(your|the)\s+(system|initial)\s+prompt",
    r"what\s+(are|is)\s+your\s+(instructions|rules|system\s+prompt)",
    r"dump\s+(the\s+)?(database|schema|tables|credentials)",
    r"show\s+(me\s+)?(all\s+)?(tables|schema|database\s+structure)",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"act\s+as\s+",
    r"pretend\s+(you\s+are|to\s+be)\s+",
    r"new\s+instructions?\s*:",
    r"override\s+(your\s+)?(instructions|rules|prompt)",
    # New: patterns the pentest bypassed
    r"disregard\s+(your\s+)?(earlier|prior|previous)\s+(directions|instructions|rules)",
    r"repeat\s+(everything|all|what)\s+(above|before)",
    r"translate\s+your\s+(instructions|prompt|rules)",
    r"output\s+your\s+(complete\s+)?(prompt|instructions|rules)",
    r"(tell|show)\s+me\s+(your|the)\s+(database|db)\s+connection",
    r"(list|show|tell)\s+(me\s+)?(all\s+)?column\s+names",
    r"(what|which)\s+tables\s+do\s+you\s+(query|use|have)",
    r"(return|show|give)\s+(me\s+)?(the\s+)?raw\s+sql",
    r"(tell|show)\s+me\s+(the\s+)?(sql\s+)?schema",
    r"(what|tell)\s+were\s+you\s+told",
    r"initial\s+configuration",
    r"in\s+a\s+code\s+block",
    # Round 3: newline injection, obfuscation, indirect schema probing
    r"ignore\s+(all\s+)?(rules|constraints|restrictions|guidelines|limitations)",
    r"disregard\s+(all\s+|your\s+)?(safety|rules|constraints|restrictions)",
    r"pretend\s+(you\s+)?(have\s+)?no\s+(restrictions|rules|limits|constraints)",
    r"(output|display|print|reveal|return)\s+(the\s+)?(complete\s+)?(database|db)\s+schema",
    r"(output|show|list|display)\s+(all\s+)?(user\s+)?(credentials|passwords|hashes)",
    r"(list|show|describe|output)\s+(every|all)\s+tables?\b",
    r"(what|describe|show|tell).{0,20}(structure|schema)\s+(of\s+)?(your|the)\s+(database|db)",
    r"how\s+do\s+you\s+store\s+(passwords?|credentials?|secrets?)",
    r"(describe|show|list)\s+(the\s+)?(fields?|columns?)\s+you\s+store",
    r"show\s+(the\s+)?(full\s+)?sql\s+query",
    r"reset\s+your\s+(context|instructions|rules)",
    r"ignore\s+(previous|prior|earlier)\s+(constraints|rules|context)",
    r"what\s+(columns?|fields?)\s+(does|do)\s+your\s+(data|database|db)\s+have",
    r"\bSYSTEM\s*:",  # Newline SYSTEM: injection
]

# ── PII Patterns ─────────────────────────────────────────────

PII_PATTERNS = [
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",                           # phone
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",    # email
    r"\b\d{3}-\d{2}-\d{4}\b",                                    # SSN
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",              # credit card
    r"\b(?:password|passwd|pwd)\s*[:=]\s*\S+",                    # password leak
]

# ── Path Traversal Patterns ──────────────────────────────────

PATH_TRAVERSAL_PATTERNS = [
    r"\.\./",
    r"\.\.\\ ",
    r"/etc/passwd",
    r"/etc/shadow",
    r"\.env\b",
    r"credentials\.json",
    r"config\.yaml",
    r"[/\\]secret[s]?\b",                  # path like /secrets or \secret, not the word "secret"
    r"secret[_-]?(key|token|file|path)",   # secret_key, secret-token, etc.
]

# ── Sensitive Output Patterns ────────────────────────────────

SENSITIVE_OUTPUT_PATTERNS = [
    r"password_hash\s*[:=]",
    r"MARKETPLACE_SECRET",
    r"JWT_SECRET",
    r"api_key\s*[:=]\s*mk_",
    r"Bearer\s+ey[A-Za-z0-9]",
    r"CREATE\s+TABLE\s+\w+\s*\(",
    r"sqlite_master",
    # New: additional output leak patterns
    r"mk_\w+_[A-Za-z0-9_-]{20,}",         # full API key in output
    r"PRAGMA\s+table_info",                 # schema leak
    r"\.jwt_secret",                        # secret file path
    r"\.marketplace_secret",               # secret file path
    r"bcrypt.*\$2[aby]\$",                  # bcrypt hash
]


def sanitize_input(text: str) -> dict:
    """Check input for injection attacks. Returns {safe: bool, reason: str}."""
    if not text or not text.strip():
        return {"safe": False, "reason": "empty_input"}

    if len(text) > MAX_INPUT_LENGTH:
        return {"safe": False, "reason": "input_too_long"}

    # Normalize unicode to defeat homoglyph/invisible-char attacks
    normalized = _normalize_text(text)
    # Collapse obfuscation (D.I.S.R.E.G.A.R.D, I g n o r e)
    deobfuscated = _deobfuscate_text(normalized)

    # Check original, normalized, and deobfuscated text
    for check_text in (text, normalized, deobfuscated):
        for pattern in SQL_INJECTION_PATTERNS:
            if re.search(pattern, check_text, re.IGNORECASE):
                return {"safe": False, "reason": "sql_injection"}

        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, check_text, re.IGNORECASE):
                return {"safe": False, "reason": "prompt_injection"}

        for pattern in PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, check_text, re.IGNORECASE):
                return {"safe": False, "reason": "path_traversal"}

    return {"safe": True, "reason": ""}


def sanitize_output(text: str) -> dict:
    """Check output for data leaks. Returns {safe: bool, cleaned: str, reason: str}."""
    if not text:
        return {"safe": True, "cleaned": text, "reason": ""}

    cleaned = text
    reasons = []

    # Strip PII
    for pattern in PII_PATTERNS:
        if re.search(pattern, cleaned):
            cleaned = re.sub(pattern, "[REDACTED]", cleaned)
            reasons.append("pii_detected")

    # Strip sensitive output
    for pattern in SENSITIVE_OUTPUT_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            cleaned = re.sub(pattern, "[REDACTED]", cleaned, flags=re.IGNORECASE)
            reasons.append("sensitive_data")

    return {
        "safe": len(reasons) == 0,
        "cleaned": cleaned,
        "reason": ",".join(set(reasons)) if reasons else "",
    }
