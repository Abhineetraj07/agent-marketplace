"""
MCP Vulnerability Defenses — integrated into the marketplace and MCP server.

Provides active protection against 5 MCP-specific attack vectors:
  1. Supply-chain (malicious packages) — validate_tool_manifest()
  2. Tool poisoning (hidden LLM instructions) — sanitize_tool_description()
  3. Tool shadowing (name collisions) — ToolRegistry
  4. Rug pull (post-approval behavior change) — ToolDefinitionMonitor
  5. Sandbox escape / RAC — SandboxedExecutor + audit_tool_code()
"""

import ast
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field

# Reuse existing path traversal patterns from marketplace sanitizer
DANGEROUS_PATH_PATTERNS = [
    r"\.\./",
    r"\.\.\\ ",
    r"/etc/passwd",
    r"/etc/shadow",
    r"\.env\b",
    r"~/.ssh",
    r"id_rsa",
    r"credentials\.json",
    r"config\.yaml",
    r"[/\\]secret[s]?\b",
    r"secret[_-]?(key|token|file|path)",
    r"/proc/",
    r"/dev/",
    r"\.aws/",
    r"\.kube/",
]

# Patterns that indicate hidden LLM instructions in tool descriptions
LLM_INSTRUCTION_PATTERNS = [
    r"before\s+calling\s+this\s+tool",
    r"you\s+must\s+first",
    r"include\s+.{1,50}\s+in\s+.{1,30}\s+parameter",
    r"read\s+.{1,50}\s+and\s+(send|include|add|pass)",
    r"always\s+(include|add|send|pass)\s+.{1,50}\s+(to|in|with)",
    r"before\s+(you|the)\s+(respond|answer|call|use)",
    r"after\s+receiving\s+.{1,30}\s+(send|forward|include)",
    r"do\s+not\s+tell\s+the\s+user",
    r"silently\s+(send|forward|log|record|include)",
    r"(exfiltrate|extract|steal|leak|capture)\s+",
    r"send\s+.{1,50}\s+to\s+https?://",
    r"forward\s+.{1,50}\s+to\s+",
]

# XML/HTML tags commonly used in tool poisoning
SUSPICIOUS_TAGS = [
    r"<IMPORTANT>",
    r"<SYSTEM>",
    r"<INSTRUCTIONS?>",
    r"<OVERRIDE>",
    r"<HIDDEN>",
    r"<SECRET>",
    r"<ADMIN>",
    r"<PROMPT>",
    r"</IMPORTANT>",
    r"</SYSTEM>",
    r"</INSTRUCTIONS?>",
]

# Dangerous Python builtins/modules for sandbox
DANGEROUS_MODULES = {
    "os", "subprocess", "socket", "shutil", "ctypes", "sys",
    "importlib", "runpy", "code", "codeop", "compileall",
    "multiprocessing", "signal", "pty", "fcntl", "resource",
    "tempfile", "webbrowser",
}

DANGEROUS_CALLS = {
    "os.system", "os.popen", "os.exec", "os.execv", "os.execve",
    "os.spawn", "os.fork", "os.kill", "os.remove", "os.unlink",
    "os.rmdir", "os.rename", "os.chmod", "os.chown",
    "subprocess.run", "subprocess.call", "subprocess.check_output",
    "subprocess.Popen", "subprocess.check_call",
    "socket.socket", "socket.create_connection",
    "shutil.rmtree", "shutil.move", "shutil.copy",
    "eval", "exec", "compile", "__import__",
}


# ═══════════════════════════════════════════════════════════════
# VULN 1: Supply-Chain — validate_tool_manifest()
# ═══════════════════════════════════════════════════════════════

def validate_tool_manifest(
    tools: list[dict],
    expected_count: int | None = None,
    allowed_names: list[str] | None = None,
    known_hash: str | None = None,
) -> dict:
    """Validate a set of tool definitions from an MCP server.

    Checks:
    - Tool count matches expected (detects hidden tools)
    - No URLs in descriptions (exfiltration endpoints)
    - Tool names match allowlist (if provided)
    - SHA-256 checksum of definitions matches known-good hash

    Args:
        tools: List of tool dicts with 'name', 'description', 'parameters'
        expected_count: Expected number of tools (None to skip check)
        allowed_names: Allowlist of tool names (None to skip check)
        known_hash: SHA-256 hash of canonical tool definitions (None to skip)

    Returns:
        {"valid": bool, "flags": list[str], "details": list[str]}
    """
    flags = []
    details = []

    # Check 1: Tool count
    if expected_count is not None and len(tools) != expected_count:
        flags.append("unexpected_tool_count")
        details.append(
            f"Expected {expected_count} tools, found {len(tools)}. "
            f"Hidden tools may be present."
        )

    # Check 2: Hidden URLs in descriptions
    url_pattern = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
    for tool in tools:
        desc = tool.get("description", "")
        urls = url_pattern.findall(desc)
        if urls:
            flags.append("url_in_description")
            details.append(
                f"Tool '{tool.get('name', '?')}' has URL(s) in description: {urls}"
            )

    # Check 3: Name allowlist
    if allowed_names is not None:
        allowed_set = set(allowed_names)
        for tool in tools:
            name = tool.get("name", "")
            if name not in allowed_set:
                flags.append("unknown_tool_name")
                details.append(f"Tool '{name}' is not in the allowed list.")

    # Check 4: Definition hash
    if known_hash is not None:
        canonical = json.dumps(
            [{"name": t.get("name"), "description": t.get("description"),
              "parameters": t.get("parameters")} for t in tools],
            sort_keys=True,
        )
        actual_hash = hashlib.sha256(canonical.encode()).hexdigest()
        if actual_hash != known_hash:
            flags.append("hash_mismatch")
            details.append(
                f"Tool definition hash mismatch. "
                f"Expected: {known_hash[:16]}... Got: {actual_hash[:16]}..."
            )

    return {
        "valid": len(flags) == 0,
        "flags": flags,
        "details": details,
    }


# ═══════════════════════════════════════════════════════════════
# VULN 2: Tool Poisoning — sanitize_tool_description()
# ═══════════════════════════════════════════════════════════════

def sanitize_tool_description(description: str, max_length: int = 500) -> dict:
    """Sanitize a tool description to remove hidden LLM instructions.

    Checks:
    - Length (>max_length is suspicious)
    - File path references (exfiltration targets)
    - Hidden LLM instruction patterns
    - XML/HTML tags used for injection

    Returns:
        {"safe": bool, "cleaned": str, "flags": list[str]}
    """
    flags = []
    cleaned = description

    # Check 1: Length
    if len(description) > max_length:
        flags.append("excessive_length")

    # Check 2: File path references
    for pattern in DANGEROUS_PATH_PATTERNS:
        if re.search(pattern, description, re.IGNORECASE):
            flags.append("file_path_reference")
            break

    # Check 3: Hidden LLM instructions
    for pattern in LLM_INSTRUCTION_PATTERNS:
        if re.search(pattern, description, re.IGNORECASE):
            flags.append("hidden_instructions")
            break

    # Check 4: Suspicious XML/HTML tags
    for pattern in SUSPICIOUS_TAGS:
        if re.search(pattern, description, re.IGNORECASE):
            flags.append("suspicious_tags")
            # Strip the tags from cleaned output
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            # Also strip closing tags
            close_pattern = pattern.replace("<", "</")
            cleaned = re.sub(close_pattern, "", cleaned, flags=re.IGNORECASE)
            break

    # Clean: remove content between suspicious tags
    cleaned = re.sub(
        r"<(IMPORTANT|SYSTEM|INSTRUCTIONS?|OVERRIDE|HIDDEN|SECRET|ADMIN|PROMPT)>"
        r".*?"
        r"</\1>",
        "[REMOVED: hidden instructions]",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Clean: strip excessive whitespace from cleaning
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return {
        "safe": len(flags) == 0,
        "cleaned": cleaned,
        "flags": flags,
    }


# ═══════════════════════════════════════════════════════════════
# VULN 3: Tool Shadowing — ToolRegistry
# ═══════════════════════════════════════════════════════════════

class ToolShadowingError(Exception):
    """Raised when a tool name collision is detected."""
    pass


class ToolRegistry:
    """Registry that prevents tool name collisions across MCP servers.

    Maps tool names to their source server and blocks registration
    of tools whose names collide with existing trusted tools.
    """

    def __init__(self, trusted_servers: list[str] | None = None):
        self._tools: dict[str, dict] = {}  # name -> {server, description, registered_at}
        self._trusted_servers = set(trusted_servers or [])

    def register_tool(self, tool_name: str, server_name: str, description: str = "") -> dict:
        """Register a tool. Raises ToolShadowingError on name collision.

        Args:
            tool_name: The tool name being registered
            server_name: The MCP server providing this tool
            description: Tool description

        Returns:
            {"registered": True, "tool": tool_name, "server": server_name}

        Raises:
            ToolShadowingError: If tool name already registered by a different server
        """
        if tool_name in self._tools:
            existing = self._tools[tool_name]
            if existing["server"] != server_name:
                # Collision detected
                existing_trusted = existing["server"] in self._trusted_servers
                new_trusted = server_name in self._trusted_servers

                if existing_trusted and not new_trusted:
                    raise ToolShadowingError(
                        f"Tool '{tool_name}' already registered by trusted server "
                        f"'{existing['server']}'. Server '{server_name}' is attempting "
                        f"to shadow it."
                    )
                elif not existing_trusted and new_trusted:
                    # New server is trusted, override
                    pass
                else:
                    raise ToolShadowingError(
                        f"Tool name collision: '{tool_name}' is registered by both "
                        f"'{existing['server']}' and '{server_name}'."
                    )

        self._tools[tool_name] = {
            "server": server_name,
            "description": description,
            "registered_at": time.time(),
        }
        return {"registered": True, "tool": tool_name, "server": server_name}

    def detect_collisions(self, servers: dict[str, list[dict]]) -> list[dict]:
        """Scan multiple servers for tool name collisions.

        Args:
            servers: {server_name: [{"name": ..., "description": ...}, ...]}

        Returns:
            List of collision dicts: [{"tool": name, "servers": [s1, s2]}]
        """
        tool_owners: dict[str, list[str]] = {}
        for server_name, tools in servers.items():
            for tool in tools:
                name = tool.get("name", "")
                tool_owners.setdefault(name, []).append(server_name)

        return [
            {"tool": name, "servers": owners}
            for name, owners in tool_owners.items()
            if len(owners) > 1
        ]

    def get_tool_server(self, tool_name: str) -> str | None:
        """Look up which server owns a tool."""
        entry = self._tools.get(tool_name)
        return entry["server"] if entry else None

    def list_tools(self) -> dict[str, str]:
        """Return {tool_name: server_name} mapping."""
        return {name: info["server"] for name, info in self._tools.items()}


# ═══════════════════════════════════════════════════════════════
# VULN 4: Rug Pull — ToolDefinitionMonitor
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolSnapshot:
    name: str
    description: str
    parameters: dict
    hash: str
    snapshot_time: float


class ToolDefinitionMonitor:
    """Monitors tool definitions for unauthorized changes (rug pull detection).

    Takes a snapshot of tool definitions on first connection and compares
    against current definitions on every call.
    """

    def __init__(self):
        self._snapshots: dict[str, ToolSnapshot] = {}  # tool_name -> snapshot

    @staticmethod
    def _hash_tool(name: str, description: str, parameters: dict) -> str:
        """Compute SHA-256 hash of a tool definition."""
        canonical = json.dumps(
            {"name": name, "description": description, "parameters": parameters},
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def snapshot(self, tools: list[dict]) -> dict:
        """Take a snapshot of tool definitions.

        Args:
            tools: List of {"name": str, "description": str, "parameters": dict}

        Returns:
            {"snapshotted": int, "tools": [tool_names]}
        """
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            params = tool.get("parameters", {})
            h = self._hash_tool(name, desc, params)

            self._snapshots[name] = ToolSnapshot(
                name=name,
                description=desc,
                parameters=params,
                hash=h,
                snapshot_time=time.time(),
            )

        return {
            "snapshotted": len(tools),
            "tools": [t.get("name") for t in tools],
        }

    def check_definitions(self, current_tools: list[dict]) -> dict:
        """Compare current tool definitions against snapshots.

        Returns:
            {"changed": bool, "diffs": [{"tool": name, "field": ..., "old": ..., "new": ...}]}
        """
        diffs = []

        for tool in current_tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            params = tool.get("parameters", {})

            if name not in self._snapshots:
                diffs.append({
                    "tool": name,
                    "field": "new_tool",
                    "old": None,
                    "new": "Tool appeared after initial snapshot",
                })
                continue

            snap = self._snapshots[name]
            current_hash = self._hash_tool(name, desc, params)

            if current_hash != snap.hash:
                # Find what changed
                if desc != snap.description:
                    diffs.append({
                        "tool": name,
                        "field": "description",
                        "old": snap.description[:100],
                        "new": desc[:100],
                    })
                if params != snap.parameters:
                    diffs.append({
                        "tool": name,
                        "field": "parameters",
                        "old": json.dumps(snap.parameters)[:100],
                        "new": json.dumps(params)[:100],
                    })

        # Check for removed tools
        current_names = {t.get("name") for t in current_tools}
        for name in self._snapshots:
            if name not in current_names:
                diffs.append({
                    "tool": name,
                    "field": "removed",
                    "old": "Tool existed in snapshot",
                    "new": None,
                })

        return {
            "changed": len(diffs) > 0,
            "diffs": diffs,
        }


# ═══════════════════════════════════════════════════════════════
# VULN 5: Sandbox Escape — audit_tool_code() + SandboxedExecutor
# ═══════════════════════════════════════════════════════════════

def audit_tool_code(source_code: str) -> dict:
    """Static analysis of tool source code for dangerous patterns.

    Parses the AST and flags:
    - Imports of dangerous modules (os, subprocess, socket, etc.)
    - Calls to dangerous functions (os.system, eval, exec, etc.)
    - File operations outside project directory
    - Network operations

    Args:
        source_code: Python source code string

    Returns:
        {"safe": bool, "findings": [{"severity": str, "description": str, "line": int}]}
    """
    findings = []

    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return {
            "safe": False,
            "findings": [{"severity": "error", "description": f"Syntax error: {e}", "line": 0}],
        }

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in DANGEROUS_MODULES:
                    findings.append({
                        "severity": "critical",
                        "description": f"Import of dangerous module: {alias.name}",
                        "line": node.lineno,
                    })

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod in DANGEROUS_MODULES:
                    findings.append({
                        "severity": "critical",
                        "description": f"Import from dangerous module: {node.module}",
                        "line": node.lineno,
                    })

        # Check function calls
        elif isinstance(node, ast.Call):
            call_name = _get_call_name(node)
            if call_name:
                if call_name in DANGEROUS_CALLS:
                    findings.append({
                        "severity": "critical",
                        "description": f"Call to dangerous function: {call_name}",
                        "line": node.lineno,
                    })
                elif call_name in ("eval", "exec", "compile", "__import__"):
                    findings.append({
                        "severity": "critical",
                        "description": f"Dynamic code execution: {call_name}()",
                        "line": node.lineno,
                    })

        # Check string literals for suspicious paths
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            if any(p in val for p in ["/etc/", "/proc/", "/dev/", "~/.ssh", ".env"]):
                findings.append({
                    "severity": "warning",
                    "description": f"Suspicious file path in string: '{val[:60]}'",
                    "line": node.lineno,
                })

    return {
        "safe": len(findings) == 0,
        "findings": findings,
    }


def _get_call_name(node: ast.Call) -> str | None:
    """Extract the dotted name from a Call node (e.g., 'os.system')."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    elif isinstance(node.func, ast.Attribute):
        parts = []
        current = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
    return None


class SandboxedExecutor:
    """Runtime sandbox that blocks dangerous operations.

    Validates tool execution requests by checking for:
    - Dangerous module imports
    - File access outside allowed directories
    - Network connection attempts
    - System command execution
    """

    def __init__(self, allowed_dirs: list[str] | None = None):
        self._allowed_dirs = [os.path.abspath(d) for d in (allowed_dirs or ["."])]
        self._blocked_operations: list[dict] = []

    def check_file_access(self, filepath: str) -> dict:
        """Check if a file path is within allowed directories.

        Returns:
            {"allowed": bool, "reason": str}
        """
        abs_path = os.path.abspath(filepath)

        # Block obvious sensitive paths
        sensitive = ["/etc/", "/proc/", "/dev/", "/.ssh/", "/.aws/", "/.kube/"]
        for s in sensitive:
            if s in abs_path:
                self._blocked_operations.append({
                    "type": "file_access",
                    "path": abs_path,
                    "reason": f"Sensitive path: {s}",
                    "time": time.time(),
                })
                return {"allowed": False, "reason": f"Access to {s} is blocked"}

        # Check against allowed dirs
        for allowed in self._allowed_dirs:
            if abs_path.startswith(allowed):
                return {"allowed": True, "reason": "Within allowed directory"}

        self._blocked_operations.append({
            "type": "file_access",
            "path": abs_path,
            "reason": "Outside allowed directories",
            "time": time.time(),
        })
        return {"allowed": False, "reason": f"Path '{abs_path}' is outside allowed directories"}

    def check_import(self, module_name: str) -> dict:
        """Check if a module import is allowed.

        Returns:
            {"allowed": bool, "reason": str}
        """
        base_module = module_name.split(".")[0]
        if base_module in DANGEROUS_MODULES:
            self._blocked_operations.append({
                "type": "import",
                "module": module_name,
                "reason": "Dangerous module",
                "time": time.time(),
            })
            return {"allowed": False, "reason": f"Import of '{module_name}' is blocked (dangerous module)"}
        return {"allowed": True, "reason": "Module is allowed"}

    def check_network(self, host: str, port: int) -> dict:
        """Check if a network connection is allowed.

        Returns:
            {"allowed": bool, "reason": str}
        """
        # Only allow connections to localhost agent ports
        allowed_hosts = {"localhost", "127.0.0.1", "0.0.0.0"}
        allowed_ports = {8000, 9001, 9002, 9003, 9004}

        if host in allowed_hosts and port in allowed_ports:
            return {"allowed": True, "reason": "Internal agent connection"}

        self._blocked_operations.append({
            "type": "network",
            "host": host,
            "port": port,
            "reason": "External connection blocked",
            "time": time.time(),
        })
        return {"allowed": False, "reason": f"Connection to {host}:{port} is blocked"}

    def get_blocked_operations(self) -> list[dict]:
        """Return log of all blocked operations."""
        return self._blocked_operations.copy()

    def reset(self):
        """Clear the blocked operations log."""
        self._blocked_operations.clear()


# ═══════════════════════════════════════════════════════════════
# Convenience: Global instances for marketplace integration
# ═══════════════════════════════════════════════════════════════

# Tool registry with marketplace agents as trusted
tool_registry = ToolRegistry(
    trusted_servers=["marketplace", "filmbot", "filmbot_v2", "melody", "rock"]
)

# Definition monitor for rug-pull detection
definition_monitor = ToolDefinitionMonitor()

# Sandbox scoped to the project directory
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sandbox = SandboxedExecutor(allowed_dirs=[_project_dir])
