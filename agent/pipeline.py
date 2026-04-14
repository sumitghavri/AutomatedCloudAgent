import streamlit as st
from agent.intent import classify_intent
from agent.extractor import extract_entities
from agent.gap_filler import fill_gaps
from agent.cost_estimator import calculate_deployment_cost
from agent.executor import (
    deploy_ec2, deploy_s3, deploy_docker_single, deploy_docker_compose
)

NON_ACTION_INTENTS = ["OUT_OF_SCOPE", "GENERAL_CHAT", "AMBIGUOUS"]

# Intents that have a real executor backing them
EXECUTABLE_INTENTS = ["EC2_DEPLOY", "S3_CREATE", "DESTROY", "VPC_SETUP","DOCKER_SINGLE", "DOCKER_COMPOSE"]


def _add_cost_summary(response_msg: str, intent: str, params: dict) -> str:
    """Appends a breakdown cost summary if estimator is enabled."""
    if not st.session_state.get("cost_estimate"):
        return response_msg
    
    costs = calculate_deployment_cost(intent, params)
    
    breakdown = f"""
---
#### 💰 Cost Estimate ({costs['currency']})
- **Infrastructure:** ${costs['infra']:.4f}/hr
- **Service/DevOps:** ${costs['service']:.4f}/hr
- **Total:** **${costs['total']:.4f}/hr** (~${costs['monthly']:.2f}/mo)
"""
    return response_msg + "\n" + breakdown


def _get_aws_creds() -> dict:
    """Pull decrypted AWS credentials from Streamlit session state."""
    return {
        "access_key": st.session_state.get("aws_access_key"),
        "secret_key": st.session_state.get("aws_secret_key"),
        "region":     st.session_state.get("aws_region", "ap-south-1"),
    }


def process_message(user_input: str, chat_history_list: list) -> str:
    """
    Main Pipeline:
    Stage 0:   Confirmation/Edit/Cancel detection
    Stage 0.5: Gap answer interception (naming, clarifications)
    Stage 1:   Intent Classification
    Stage 2:   Entity Extraction
    Stage 3:   Gap Filling
    Stage 4:   Execution
    """
    recent  = chat_history_list[-6:] if len(chat_history_list) > 6 else chat_history_list
    context = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in recent])

    # -----------------------------------------------------------------------
    # Stage 0: Pending confirmation (yes/no/edit)
    # -----------------------------------------------------------------------
    if len(chat_history_list) >= 2:
        second_to_last = chat_history_list[-2]
        content_last = second_to_last.get("content", "")
        if (
            second_to_last.get("role") == "assistant"
            and ("Shall I proceed to generate the configuration?" in content_last or 
                 "Shall I proceed to execute the teardown?" in content_last or
                 "Shall I proceed to create the VPC" in content_last or 
                 "Shall I proceed to create the bucket?" in content_last)
        ):
            lower = user_input.lower().strip()

            if lower in ["yes", "y", "sure", "proceed", "go", "do it", "yep", "yeah"]:
                pending        = st.session_state.get("pending_deploy_params")
                pending_intent = st.session_state.get("pending_deploy_intent")
                if not pending or not pending_intent:
                    return "⚠️ I lost the deployment context. Please describe what you'd like to deploy again."
                if pending_intent == "EC2_DEPLOY":
                    aws_creds = _get_aws_creds()
                    if not aws_creds.get("access_key"):
                        return (
                            "⚠️ **No AWS credentials found in your profile.**\n\n"
                            "Please go to **Profile & Settings → AWS** and enter your IAM Access Key and Secret."
                        )
                    pending["auto_teardown"] = st.session_state.get("auto_teardown", False)
                    with st.spinner("Launching EC2 instance(s)... this may take 1-2 minutes..."):
                        result = deploy_ec2(pending, aws_creds)
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    # Track deployed resources in memory
                    if result.get("success"):
                        st.session_state['last_instance'] = result
                        mem = st.session_state.setdefault("deployed_resources", [])
                        servers = pending.get("servers") or [pending]
                        for s in servers:
                            mem.append({"type": "EC2", "name": s.get("name_tag", "server"),
                                        "region": pending.get("region", "ap-south-1"), "os": s.get("os", "ubuntu")})
                    return result["message"]
                elif pending_intent == "S3_CREATE":
                    aws_creds = _get_aws_creds()
                    if not aws_creds.get("access_key"):
                        return (
                            "⚠️ **No AWS credentials found in your profile.**\n\n"
                            "Please go to **Profile & Settings → AWS** and enter your IAM Access Key and Secret."
                        )
                    with st.spinner("Creating S3 Bucket..."):
                        result = deploy_s3(pending, aws_creds)
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    if result.get("status") == "success":
                        st.session_state['active_bucket'] = pending.get("bucket_name")
                        st.session_state['show_s3_dialog'] = True
                        mem = st.session_state.setdefault("deployed_resources", [])
                        mem.append({"type": "S3", "name": pending.get("bucket_name", "bucket"),
                                    "region": pending.get("region", "ap-south-1"), "os": "-"})
                    return result["message"]
                elif pending_intent == "DESTROY":
                    aws_creds = _get_aws_creds()
                    if not aws_creds.get("access_key"):
                        return "⚠️ **No AWS credentials found in your profile.**"
                    with st.spinner(f"Destroying resource(s)..."):
                        from agent.executor import destroy_aws_resource
                        result = destroy_aws_resource(pending, aws_creds)
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    # Clear matching entries from memory
                    identifier = pending.get("resource_identifier", "")
                    if identifier == "all":
                        st.session_state["deployed_resources"] = []
                    elif isinstance(identifier, list):
                        st.session_state["deployed_resources"] = [
                            r for r in st.session_state.get("deployed_resources", [])
                            if r["name"] not in identifier
                        ]
                    return result["message"]
                elif pending_intent == "VPC_SETUP":
                    aws_creds = _get_aws_creds()
                    if not aws_creds.get("access_key"):
                        return "⚠️ **No AWS credentials found in your profile.**"
                    with st.spinner("Building VPC Architecture..."):
                        from agent.executor import deploy_vpc
                        result = deploy_vpc(pending, aws_creds)
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    if result.get("status") == "success":
                        mem = st.session_state.setdefault("deployed_resources", [])
                        mem.append({"type": "VPC", "name": pending.get("vpc_name", "AICloudAgent-VPC"),
                                    "region": pending.get("region", "ap-south-1"), "os": "-"})
                    return result["message"]
                elif pending_intent == "DOCKER_SINGLE":
                    aws_creds = _get_aws_creds()
                    if not aws_creds.get("access_key"):
                        return "⚠️ **No AWS credentials found in your profile.**"
                    with st.spinner("🐳 Launching Docker container... this takes 2-3 minutes..."):
                        result = deploy_docker_single(pending, aws_creds)
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    if result.get("success"):
                        mem = st.session_state.setdefault("deployed_resources", [])
                        mem.append({"type": "Docker", "name": pending.get("name_tag", "container"),
                                    "region": pending.get("region", "ap-south-1"), "os": "ubuntu"})
                    return result["message"]
                elif pending_intent == "DOCKER_COMPOSE":
                    aws_creds = _get_aws_creds()
                    if not aws_creds.get("access_key"):
                        return "⚠️ **No AWS credentials found in your profile.**"
                    with st.spinner("🐳 Launching Docker Compose stack... this takes 3-4 minutes..."):
                        result = deploy_docker_compose(pending, aws_creds)
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    if result.get("success"):
                        mem = st.session_state.setdefault("deployed_resources", [])
                        mem.append({"type": "Compose", "name": pending.get("name_tag", "stack"),
                                    "region": pending.get("region", "ap-south-1"), "os": "ubuntu"})
                    return result["message"]
                else:
                    st.session_state.pop("pending_deploy_params", None)
                    st.session_state.pop("pending_deploy_intent", None)
                    return (
                        f"🚀 **Confirmed!** Generating configuration for `{pending_intent}`...\n\n"
                        f"*(Stage 4 executor for {pending_intent} is coming in the next update!)*"
                    )
                
            elif lower in ["no", "n", "cancel", "stop", "abort", "nope", "nah"]:
                st.session_state.pop("pending_deploy_params", None)
                st.session_state.pop("pending_deploy_intent", None)
                return "❌ Deployment cancelled. What would you like to build instead?"

            else:
                # EDIT path
                pending        = st.session_state.get("pending_deploy_params")
                pending_intent = st.session_state.get("pending_deploy_intent")
                if not pending or not pending_intent:
                    return "⚠️ I lost the deployment context. Please describe what you'd like to deploy again."

                try:
                    edits = extract_entities(pending_intent, user_input, context, pending_params=pending)
                except Exception as e:
                    return f"*(System Error during edit extraction)*: {str(e)}"

                if edits.get("__edit_mode__"):
                    changes    = edits.get("changes", {}) or {}
                    server_idx = edits.get("server_index")
                    count      = int(pending.get("count") or 1)

                    # Expand flat config into servers list if needed
                    if not pending.get("servers") or not isinstance(pending["servers"], list):
                        base = {
                            "os":            pending.get("os", "ubuntu"),
                            "instance_type": pending.get("instance_type", "t2.micro"),
                            "ports":         pending.get("ports") or [22, 80],
                            "key_pair":      pending.get("key_pair"),
                        }
                        pending["servers"] = []
                        for i in range(count):
                            entry = dict(base)
                            entry["name_tag"] = (
                                f"{pending.get('name_tag', 'server')}-{i+1}"
                                if count > 1 else pending.get("name_tag")
                            )
                            pending["servers"].append(entry)

                    real_changes = {k: v for k, v in changes.items() if v is not None}
                    if server_idx is not None:
                        if 0 <= server_idx < len(pending["servers"]):
                            pending["servers"][server_idx].update(real_changes)
                    else:
                        for s in pending["servers"]:
                            s.update(real_changes)

                    if pending["servers"]:
                        pending["name_tag"] = pending["servers"][0].get("name_tag", pending.get("name_tag"))
                else:
                    for key, val in edits.items():
                        if val is not None:
                            pending[key] = val

                final_params, response_msg, ready = fill_gaps(pending_intent, pending)
                if ready:
                    st.session_state["pending_deploy_params"] = final_params
                    st.session_state["pending_deploy_intent"] = pending_intent
                    response_msg = _add_cost_summary(response_msg, pending_intent, final_params)
                return response_msg

    # -----------------------------------------------------------------------
    # Stage 0.5: Gap answer interception
    # If there's an incomplete deployment in session state (ready=False was
    # returned), treat this message as the answer to the pending gap question
    # instead of running the full pipeline from scratch.
    # -----------------------------------------------------------------------
    incomplete = st.session_state.get("incomplete_deploy_params")
    incomplete_intent = st.session_state.get("incomplete_deploy_intent")

    if incomplete and incomplete_intent:
        count = int(incomplete.get("count") or 1)

        if incomplete_intent == "EC2_DEPLOY":
            # Extract any property edits included in the gap answer (e.g. 'type is t3 micro')
            try:
                edits = extract_entities(incomplete_intent, user_input, context)
            except Exception:
                edits = {}

            # Preserve existing servers list (keeps per-server OS/type intact)
            # Only rebuild from scratch if it doesn't exist yet
            if not incomplete.get("servers") or not isinstance(incomplete["servers"], list):
                incomplete["servers"] = []
                for i in range(count):
                    incomplete["servers"].append({
                        "os":            incomplete.get("os") or "ubuntu",
                        "instance_type": incomplete.get("instance_type") or "t2.micro",
                        "ports":         incomplete.get("ports") or [22, 80],
                        "key_pair":      incomplete.get("key_pair"),
                        "name_tag":      None,
                    })

            # Apply any non-name property edits found in this gap answer!
            for k, v in edits.items():
                if v is not None and k not in ("name_tag", "servers", "count"):
                    incomplete[k] = v
                    for s in incomplete["servers"]:
                        s[k] = v

            raw = user_input.strip()
            import re as _re
            
            # Clean up the string by removing property declarations before splitting names
            name_clean = _re.sub(r'\b(type is|os is|port is|name the server as|name it|name)\b', '', raw, flags=_re.IGNORECASE)
            
            parts = [p.strip() for p in _re.split(r',|;|\band\b', name_clean, flags=_re.IGNORECASE) if p.strip()]
            parts = [p for p in parts if p.lower() not in ("respectively", "each", "both")]
            # Filter out parts that contain instance types or OS names heavily
            parts = [p for p in parts if not _re.search(r'\b(t2|t3|m5|c4|ubuntu|linux|windows|micro|large|port)\b', p, _re.IGNORECASE)]

            # If our filtering destroyed all parts, fallback to Gemini's extracted name_tag if available
            if not parts and edits.get("name_tag"):
                parts = [edits["name_tag"]]

            # Assign names positionally
            if parts:
                if len(parts) == 1:
                    base = parts[0]
                    for i, s in enumerate(incomplete["servers"]):
                        if not s.get("name_tag"):
                            s["name_tag"] = f"{base}-{i+1}" if count > 1 else base
                else:
                    for i, s in enumerate(incomplete["servers"]):
                        if not s.get("name_tag"):
                            name = parts[i] if i < len(parts) else f"{parts[-1]}-{i+1}"
                            s["name_tag"] = name

            incomplete["name_tag"] = incomplete["servers"][0].get("name_tag", "server")
            
        elif incomplete_intent == "S3_CREATE":
            try:
                edits = extract_entities(incomplete_intent, user_input, context)
            except Exception:
                edits = {}
            for k, v in edits.items():
                if v is not None:
                    incomplete[k] = v
            # If no bucket_name found via LLM, and we know this answers the naming prompt:
            if not edits.get("bucket_name"):
                incomplete["bucket_name"] = user_input.strip().split()[0].lower()

        st.session_state.pop("incomplete_deploy_params", None)
        st.session_state.pop("incomplete_deploy_intent", None)

        final_params, response_msg, ready = fill_gaps(incomplete_intent, incomplete)
        if ready:
            st.session_state["pending_deploy_params"] = final_params
            st.session_state["pending_deploy_intent"] = incomplete_intent
            response_msg = _add_cost_summary(response_msg, incomplete_intent, final_params)
        else:
            st.session_state["incomplete_deploy_params"] = final_params
            st.session_state["incomplete_deploy_intent"] = incomplete_intent
        return response_msg

    # -----------------------------------------------------------------------
    # Stage 1: Intent Classification
    # -----------------------------------------------------------------------
    try:
        intent_result = classify_intent(user_input, context)
    except Exception as e:
        return f"*(System Error during Intent Classification)*: {str(e)}"

    intent  = intent_result.get("intent", "GENERAL_CHAT")
    message = intent_result.get("message", "")

    if intent in NON_ACTION_INTENTS:
        return message or "I'm not sure how to help with that. Try asking about EC2, S3, VPC, or Docker!"

    # -----------------------------------------------------------------------
    # Stage 2: Entity Extraction
    # -----------------------------------------------------------------------
    try:
        extracted = extract_entities(intent, user_input, context)
    except Exception as e:
        return f"*(System Error during Entity Extraction)*: {str(e)}"

    # -----------------------------------------------------------------------
    # Stage 3: Gap Filling
    # -----------------------------------------------------------------------
    final_params, response_msg, ready = fill_gaps(intent, extracted)

    if ready:
        st.session_state["pending_deploy_params"] = final_params
        st.session_state["pending_deploy_intent"] = intent
        response_msg = _add_cost_summary(response_msg, intent, final_params)
    else:
        # Save incomplete params so Stage 0.5 can pick them up next message
        st.session_state["incomplete_deploy_params"] = final_params
        st.session_state["incomplete_deploy_intent"] = intent

    return response_msg
