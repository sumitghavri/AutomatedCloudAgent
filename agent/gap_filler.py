from typing import Dict, Any, Tuple

def fill_gaps(intent: str, parameters: Dict[str, Any]) -> Tuple[Dict[str, Any], str, bool]:
    """
    Stage 3: Gap Filling.
    Takes parsed parameters and applies defaults, asks clarifying questions, 
    or infers context.
    
    Returns: (updated_parameters, response_message, is_ready_to_plan)
    """
    ready = True
    msg = ""
    params = dict(parameters)  # copy to mutate

    # Global safe defaults
    if "region" in params and params["region"] is None:
        params["region"] = "ap-south-1"
        
    if "instance_type" in params and params["instance_type"] is None:
        params["instance_type"] = "t2.micro"

    # Intent specific evaluation
    if intent == "EC2_DEPLOY":
# Safely parse count — derive from servers list if not explicitly set
        try:
            raw_count = params.get("count")
            servers_list = params.get("servers")
            if raw_count:
                count = max(1, int(raw_count))
            elif servers_list and isinstance(servers_list, list):
                count = len(servers_list)   # ← use servers list length as count
            else:
                count = 1
        except (TypeError, ValueError):
            count = 1
        params["count"] = count        

        # Set base defaults — but ONLY if no per-server servers list exists
        # (don't let base os override per-server os values)
        has_servers = bool(params.get("servers") and isinstance(params["servers"], list))

        if not params.get("region"):
            params["region"] = "ap-south-1"
        if not params.get("instance_type"):
            params["instance_type"] = "t2.micro"
        if not has_servers and not params.get("os"):
            params["os"] = "ubuntu"

        # Build the servers list
        if has_servers:
            filled_servers = []
            for i in range(count):
                if i < len(params["servers"]):
                    s = dict(params["servers"][i])
                else:
                    s = {}
                # Only fill from base if the server didn't specify its own value
                if not s.get("os"):
                    s["os"] = params.get("os") or "ubuntu"
                if not s.get("instance_type"):
                    s["instance_type"] = params.get("instance_type") or "t2.micro"
                if not s.get("ports"):
                    s["ports"] = params.get("ports") or [22, 80]
                if not s.get("key_pair"):
                    s["key_pair"] = params.get("key_pair")
                filled_servers.append(s)
            params["servers"] = filled_servers
        else:
            params["servers"] = None

        # Name resolution
        # Name resolution
        if params.get("servers") and isinstance(params["servers"], list):
            if all(s.get("name_tag") for s in params["servers"]):
                params["name_tag"] = params["servers"][0]["name_tag"]
            else:
                unnamed = [i+1 for i, s in enumerate(params["servers"]) if not s.get("name_tag")]
                ready = False
                # Show per-server config so user knows what they're naming
                server_summary = ""
                for i, s in enumerate(params["servers"], 1):
                    server_summary += (
                        f"  Server {i}: OS=`{s.get('os','ubuntu')}` "
                        f"Type=`{s.get('instance_type','t2.micro')}`\n"
                    )
                if len(unnamed) == count:
                    msg = (
                        f"What should I name the {count} servers?\n\n"
                        f"{server_summary}\n"
                        f"Give individual names like: `web, db` or a base name like `myserver` "
                        f"and I'll number them → `myserver-1`, `myserver-2`..."
                    )
                else:
                    msg = (
                        f"What should I name server(s) {', '.join(map(str, unnamed))}?\n\n"
                        f"{server_summary}"
                    )
        elif not params.get("name_tag"):
            ready = False
            # Single OS or same-config multi-server
            os_label   = params.get("os", "ubuntu")
            type_label = params.get("instance_type", "t2.micro")
            msg = (
                f"What should I name the {count} server(s)? "
                f"(OS: `{os_label}`, Type: `{type_label}`)\n\n"
                f"Give individual names like: `web, db` or a base name like `myserver` "
                f"and I'll number them → `myserver-1`, `myserver-2`..."
            )
        # Assuming AWS will handle lack of Keypair or we can skip it for a pure basic server unless SSH is strictly needed
        
    elif intent == "S3_CREATE":
        if not params.get("bucket_name"):
            ready = False
            msg = "What should we name the S3 bucket? (It must be globally unique)"
        else:
            if params.get("region") is None:
                params["region"] = "ap-south-1"
            if params.get("public_access") is None:
                params["public_access"] = False
            if params.get("versioning") is None:
                params["versioning"] = False
                
            region = params["region"]
            pub    = "Public" if params["public_access"] else "Private"
            ver    = "Enabled" if params["versioning"] else "Disabled"
            
            msg = f"""Here's what I'll deploy:
- **Bucket**: `{params['bucket_name']}`
- **Region**: `{region}`
- **Access**: `{pub}`
- **Versioning**: `{ver}`

Shall I proceed to create the bucket? (yes/no)"""

    elif intent == "VPC_SETUP":
        if not params.get("region"):
            params["region"] = "ap-south-1"
        if not params.get("cidr_block"):
            params["cidr_block"] = "10.0.0.0/16"
        if not params.get("subnet_count"):
            params["subnet_count"] = 2
        if not params.get("vpc_name"):
            params["vpc_name"] = "AICloudAgent-VPC"
        # Default to public subnets (NAT disabled), user can request NAT explicitly later
        params["enable_nat_gateway"] = False
        
        region = params["region"]
        cidr   = params["cidr_block"]
        count  = params["subnet_count"]
        name   = params["vpc_name"]
        nat    = "Disabled (All Public Subnets)"
        
        msg = f"""Here's what I'll deploy:
- **VPC Name**: `{name}`
- **VPC CIDR**: `{cidr}`
- **Subnets**: `{count}` public subnets (auto-spread across Availability Zones)
- **Internet Gateway**: Will be created and attached ✅
- **Region**: `{region}`
- **NAT Gateway**: `{nat}`

Shall I proceed to create the VPC architecture? (yes/no)"""
        
        return params, msg, True

    elif intent == "DOCKER_SINGLE":
        if not params.get("image"):
            ready = False
            msg = "Which Docker image would you like to run? (e.g. nginx or a GHCR url)"
        if not params.get("port"):
            params["port"] = 80
        if not params.get("tag"):
            params["tag"] = "latest"

    elif intent == "DOCKER_COMPOSE":
        if not params.get("app_image"):
            ready = False
            msg = "What is the primary application image you want to deploy?"
        if not params.get("db_type"):
            ready = False
            msg = "What database type should this be paired with? (e.g. postgres, mysql, redis)"
        if not params.get("db_version") and params.get("db_type") == "postgres":
            params["db_version"] = "15"
        elif not params.get("db_version"):
            params["db_version"] = "latest"
        if not params.get("app_port"):
            params["app_port"] = 80

    elif intent == "DESTROY":
        import re as _re
        raw_id = (params.get("resource_identifier") or "").strip()
        
        if not raw_id:
            return params, "I need the name or ID of the resource(s) you want to destroy. Or say **'all'** to terminate everything deployed by this agent.", False
        
        # Normalize "all the servers / all ec2 / all the instances" → "all"
        all_pattern = _re.compile(
            r'^(terminate|destroy|kill|delete)?\s*(all\s*(the|of\s*the|my)?\s*(servers?|instances?|ec2s?|resources?|vms?|machines?)?|everything)$',
            _re.IGNORECASE
        )
        if all_pattern.match(raw_id) or raw_id.lower() in ["all", "all servers", "all the servers", "all instances", "everything"]:
            raw_id = "all"
        
        # Parse comma-separated or "name1 to name2" range patterns into a list
        # e.g. "ubuserver2-1, ubuserver2-2" or "ubuserver2-1 to ubuserver2-6"
        identifiers = []
        range_match = _re.match(r'(.+?)\s+to\s+(.+)', raw_id, _re.IGNORECASE)
        if range_match and raw_id != "all":
            start_name = range_match.group(1).strip()
            end_name   = range_match.group(2).strip()
            # Try to expand numeric suffix range e.g. "ubuserver2-1" to "ubuserver2-6"
            num_start = _re.search(r'(\d+)$', start_name)
            num_end   = _re.search(r'(\d+)$', end_name)
            if num_start and num_end:
                base = _re.sub(r'\d+$', '', start_name)
                s, e = int(num_start.group(1)), int(num_end.group(1))
                identifiers = [f"{base}{i}" for i in range(s, e + 1)]
        
        if not identifiers and raw_id != "all":
            # Comma-separated list
            parts = [p.strip() for p in _re.split(r'[,;]', raw_id) if p.strip()]
            identifiers = parts if len(parts) > 1 else []
        
        if identifiers:
            params["resource_identifier"] = identifiers
            id_display = "\n".join(f"  - `{i}`" for i in identifiers)
            warning_msg = f"⚠️ **WARNING**: You are about to destroy **{len(identifiers)} resources**:\n{id_display}"
        elif raw_id == "all":
            params["resource_identifier"] = "all"
            warning_msg = "⚠️ **WARNING**: You are about to **terminate ALL resources** deployed by this agent."
        else:
            params["resource_identifier"] = raw_id
            warning_msg = f"⚠️ **WARNING**: You are about to destroy `{raw_id}`."
        
        return params, f"{warning_msg}\n\nShall I proceed to execute the teardown? (yes/no)", True

    elif intent == "MONITORING":
        if not params.get("resource_identifier"):
            ready = False
            msg = "Which resource name/ID should I attach monitoring alarms to?"

    # If it's ready, formulate a confirmation message
    if ready:
        servers = params.get("servers")
        if servers and isinstance(servers, list) and len(servers) > 1:
            msg = f"Here's what I'll deploy — **{len(servers)} servers**:\n\n"
            for i, s in enumerate(servers, 1):
                msg += f"**Server {i}** — `{s.get('name_tag', f'server-{i}')}`\n"
                msg += f"- OS: `{s.get('os', 'ubuntu')}`\n"
                msg += f"- Type: `{s.get('instance_type', 't2.micro')}`\n"
                msg += f"- Ports: `{s.get('ports', [22, 80])}`\n\n"
            msg += f"📍 Region: `{params.get('region', 'ap-south-1')}`\n"
        else:
            msg = "Here's what I'll deploy:\n"
            for k, v in params.items():
                if v is not None and k != "servers":
                    msg += f"- **{k}**: {v}\n"
        msg += "\nShall I proceed to generate the configuration? (yes/no)"
    return params, msg, ready  # ← THIS LINE WAS MISSING
