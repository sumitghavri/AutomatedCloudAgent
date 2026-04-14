import re
import json
from typing import Optional
from agent.llm import invoke_gemini

# ---------------------------------------------------------------------------
# Deterministic OS normalization
# ---------------------------------------------------------------------------
OS_NORMALIZE = {
    "ubuntu":          "ubuntu",
    "ubuntu 22":       "ubuntu",
    "ubuntu 20":       "ubuntu",
    "ubuntu 18":       "ubuntu",
    "amazon linux":    "amazon-linux",
    "amazon-linux":    "amazon-linux",
    "amazonlinux":     "amazon-linux",
    "amazon linux 2":  "amazon-linux-2",
    "amazon-linux-2":  "amazon-linux-2",
    "al2":             "amazon-linux-2",
    "debian":          "debian",
    "deb":             "debian",
    "windows":         "windows",
    "win":             "windows",
    "windows server":  "windows",
    "win server":      "windows",
}

# Deterministic patterns
INSTANCE_RE = re.compile(
    r'\b('
    r't[234][ag]?[.\s]\w+'      # t2, t3, t3a, t4g
    r'|m[4-7][ag]?[.\s]\w+'     # m4-m7, m6a, m7g etc
    r'|c[4-9][ag]?[.\s]\w+'     # c4-c9, c5a, c6g etc
    r'|r[4-9][ag]?[.\s]\w+'     # r4-r9, r6g etc
    r'|g[3-5][ag]?[.\s]\w+'     # g3-g5, g4ad etc
    r'|p[234][ag]?[.\s]\w+'     # p2-p4
    r'|i[34][ag]?[.\s]\w+'      # i3, i4g
    r'|x[12][a-z]*[.\s]\w+'     # x1, x2
    r'|z1d[.\s]\w+'             # z1d
    r'|inf[12][.\s]\w+'         # inf1, inf2
    r')\b',
    re.IGNORECASE
)

REGION_RE = re.compile(
    r'\b(us-east-[12]|us-west-[12]|eu-west-[123]|eu-central-1|'
    r'ap-south-1|ap-southeast-[12]|ap-northeast-[123]|'
    r'ca-central-1|sa-east-1|me-south-1|af-south-1)\b',
    re.IGNORECASE
)
COUNT_WORDS = {
    "one":1,"two":2,"three":3,"four":4,"five":5,
    "six":6,"seven":7,"eight":8,"nine":9,"ten":10
}
COUNT_RE = re.compile(
    r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b'
    r'\s*(?:server|instance|ec2|machine|vm)s?\b',
    re.IGNORECASE
)
PORT_RE  = re.compile(r'\bport[s]?\s*[:\-]?\s*([\d,\s]+)\b', re.IGNORECASE)


def _normalize_os(text: str) -> Optional[str]:
    lower = text.lower().strip()
    for phrase in sorted(OS_NORMALIZE.keys(), key=len, reverse=True):
        if phrase in lower:
            return OS_NORMALIZE[phrase]
    return None


def _parse_ec2_deterministic(user_input: str) -> dict:
    """
    Deterministic parser — handles OS, count, instance type, region, ports.
    Never wrong on these fields. LLM only handles name_tag and key_pair.
    """
    lower = user_input.lower()

    # Count
    count = None
    m = COUNT_RE.search(lower)
    if m:
        val = m.group(1).lower()
        count = COUNT_WORDS.get(val, int(val) if val.isdigit() else None)

    # Instance type
    m = INSTANCE_RE.search(user_input)
    instance_type = m.group(0).lower().replace(" ", ".") if m else None

    # Region
    m = REGION_RE.search(user_input)
    region = m.group(0).lower() if m else None

    # Ports
    ports = None
    m = PORT_RE.search(user_input)
    if m:
        raw_ports = re.findall(r'\d+', m.group(1))
        ports = [int(p) for p in raw_ports if 1 <= int(p) <= 65535]

    # OS — split on delimiters to find all mentioned OSes
    segments  = re.split(r'\band\b|,|;|the other|another', lower)
    found_os  = []
    for seg in segments:
        os = _normalize_os(seg)
        if os and os not in found_os:
            found_os.append(os)

    result = {
        "count":         count,
        "instance_type": instance_type,
        "region":        region,
        "ports":         ports,
        "key_pair":      None,
        "name_tag":      None,
        "os":            None,
        "post_install_commands": None,
        "servers":       None,
    }

    if len(found_os) > 1:
        result["servers"] = [
            {"os": os, "name_tag": None, "instance_type": instance_type, "ports": ports}
            for os in found_os
        ]
        result["count"] = result["count"] or len(found_os)
    elif len(found_os) == 1:
        result["os"]    = found_os[0]
        result["count"] = result["count"] or 1

    return result


# ---------------------------------------------------------------------------
# Ordinal mapping for edit mode
# ---------------------------------------------------------------------------
ORDINAL_WORDS = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
    "sixth": 5, "seventh": 6, "eighth": 7, "ninth": 8, "tenth": 9,
    "eleventh": 10, "twelfth": 11, "thirteenth": 12, "fourteenth": 13,
    "fifteenth": 14, "sixteenth": 15, "seventeenth": 16, "eighteenth": 17,
    "nineteenth": 18, "twentieth": 19,
}

SCHEMA_DESCRIPTIONS = {
    "EC2_DEPLOY": """Extract ONLY these fields from the user message (null if not mentioned):
- name_tag: server name/tag if explicitly given (string or null)
- key_pair: SSH key pair name if mentioned (string or null)
- ports: list of port numbers if mentioned e.g. [80, 443, 22] (list or null)
- os: operating system if mentioned. Normalize to one of: ubuntu, amazon-linux, amazon-linux-2, debian, windows (string or null)
- instance_type: aws instance type if mentioned. Normalize to valid explicit AWS format e.g. t3.micro, m5.large (string or null)
- post_install_commands: array of bash commands to execute on the server if the user asked to install/configure software (e.g. ["sudo apt update", "sudo apt install nginx -y"]) (list of strings or null)

Respond with ONLY valid JSON, no explanation.""",

    "S3_CREATE": """Extract (null if not mentioned):
- bucket_name, region, public_access (bool), versioning (bool)
Respond ONLY valid JSON.""",

    "VPC_SETUP": """Extract from the user message (null if not mentioned):
- cidr_block: IP CIDR block e.g. '10.0.0.0/16' (string or null)
- region: AWS region e.g. 'ap-south-1' (string or null)
- subnet_count: number of subnets requested (int or null)
- enable_nat_gateway: true if user explicitly requests NAT or private subnets (bool or null)
- vpc_name: custom VPC name if user specified (string or null)
Respond ONLY valid JSON.""",

    "DOCKER_SINGLE": """Extract (null if not mentioned):
- image, tag, port (int), env_vars (list of KEY=VALUE strings), region, instance_type
Respond ONLY valid JSON.""",

    "DOCKER_COMPOSE": """Extract (null if not mentioned):
- app_image, db_type, app_port (int), db_version, region, instance_type
Respond ONLY valid JSON.""",

    "DESTROY": """Extract (null if not mentioned):
- resource_identifier, confirm (true if user confirmed else null)
Respond ONLY valid JSON.""",

    "MONITORING": """Extract (null if not mentioned):
- resource_identifier, metric_type (cpu/logs/status/memory)
Respond ONLY valid JSON.""",
}


def detect_server_index(user_input: str) -> Optional[int]:
    lower = user_input.lower()
    for word, idx in ORDINAL_WORDS.items():
        if word in lower:
            return idx
    m = re.search(r'server\s*(\d+)', lower)
    if m:
        return int(m.group(1)) - 1
    m = re.search(r'\b(\d+)(?:st|nd|rd|th)\b', lower)
    if m:
        return int(m.group(1)) - 1
    return None


def extract_entities(intent: str, user_input: str, chat_history: str = "",
                     pending_params: dict = None) -> dict:
    """
    Two-layer extraction:
    Layer 1 — Deterministic regex (OS, count, instance type, region, ports) — always correct
    Layer 2 — Gemini 2.0 Flash (name_tag, key_pair, freeform fields) — reliable JSON
    Edit mode — Gemini with deterministic OS injection
    """
    if intent not in SCHEMA_DESCRIPTIONS:
        return {}

    # -----------------------------------------------------------------------
    # EDIT MODE
    # -----------------------------------------------------------------------
    if pending_params is not None and intent == "EC2_DEPLOY":
        existing_servers = pending_params.get("servers") or []
        existing_json    = json.dumps(existing_servers, indent=2)
        server_index     = detect_server_index(user_input)
        detected_os      = _normalize_os(user_input)

        # Deterministic instance type detection for edit
        m_inst = INSTANCE_RE.search(user_input)
        detected_instance_type = m_inst.group(0).lower() if m_inst else None

        prompt = f"""You are editing an EC2 deployment config.

Current servers:
{existing_json}

Respond ONLY with this exact JSON structure:
{{
  "server_index": <0-based int or null>,
  "changes": {{
    "name_tag": <string or null>,
    "os": <exactly one of: ubuntu/amazon-linux/amazon-linux-2/debian/windows — or null>,
    "instance_type": <string or null>,
    "ports": <list or null>,
    "post_install_commands": <list of strings or null>
  }}
}}

Rules:
- "second"/"2nd"/"server 2" → server_index: 1
- "first"/"1st"/"server 1" → server_index: 0
- No position mentioned → server_index: null (applies to all)
- {len(existing_servers)} total servers, index range 0–{max(0, len(existing_servers)-1)}
- null means no change for that field

User: {user_input}"""

        try:
            content    = invoke_gemini(prompt)
            json_match = re.search(r'\{.*?\}', content, re.DOTALL)
            if json_match:
                parsed  = json.loads(json_match.group())
                changes = parsed.setdefault("changes", {})
                # Inject deterministic values if Gemini missed them
                if detected_os and not changes.get("os"):
                    changes["os"] = detected_os
                if detected_instance_type and not changes.get("instance_type"):
                    changes["instance_type"] = detected_instance_type
                parsed["__edit_mode__"] = True
                return parsed
        except Exception:
            pass

        # Full deterministic fallback
        det_changes = {}
        if detected_os:
            det_changes["os"] = detected_os
        if detected_instance_type:
            det_changes["instance_type"] = detected_instance_type
        return {
            "__edit_mode__": True,
            "server_index":  server_index,
            "changes":       det_changes,
        }

    # -----------------------------------------------------------------------
    # EC2_DEPLOY — deterministic first, Gemini for freeform fields
    # -----------------------------------------------------------------------
    if intent == "EC2_DEPLOY":
        # Layer 1: deterministic — always trust these
        det = _parse_ec2_deterministic(user_input)

        # Layer 2: Gemini for name_tag, key_pair, ports (if not caught by regex)
        prompt = f"""Extract from this message (null if not mentioned):
- name_tag: explicit server name/label given by user (null if not given)
- key_pair: SSH key pair name (null if not mentioned)
- ports: list of port numbers like [80, 443] (null if not mentioned)
- os: operating system, normalized to ubuntu/amazon-linux/amazon-linux-2/debian/windows (null if not mentioned)
- instance_type: AWS instance type, normalized to correct dot format e.g. t3.micro (null if not mentioned)
- post_install_commands: literal bash commands matching the user's installation requests (list of strings or null)

Respond ONLY with valid JSON. No explanation.
Message: {user_input}"""

        try:
            content    = invoke_gemini(prompt)
            json_match = re.search(r'\{.*?\}', content, re.DOTALL)
            if json_match:
                llm_fields = json.loads(json_match.group())
                # Merge: deterministic values take priority
                det["name_tag"] = llm_fields.get("name_tag")
                det["key_pair"] = llm_fields.get("key_pair")
                det["post_install_commands"] = llm_fields.get("post_install_commands")
                if not det.get("ports") and llm_fields.get("ports"):
                    det["ports"] = llm_fields["ports"]
                
                # Use LLM to cleanly repair any typos the regex missed
                llm_os = llm_fields.get("os")
                if not det.get("os") and llm_os:
                    det["os"] = llm_os
                    
                llm_type = llm_fields.get("instance_type")
                if not det.get("instance_type") and llm_type:
                    det["instance_type"] = llm_type
        except Exception:
            pass

        return det

    # -----------------------------------------------------------------------
    # All other intents — Gemini handles the full extraction
    # -----------------------------------------------------------------------
    schema_desc = SCHEMA_DESCRIPTIONS[intent]
    prompt = f"""You are an entity extractor for a cloud agent.
Intent: {intent}

{schema_desc}

Context: {chat_history or "None"}
User: {user_input}"""

    try:
        content    = invoke_gemini(prompt)
        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {}
    except Exception:
        return {}