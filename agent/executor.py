import boto3
import time
import os
import traceback
import ipaddress
from botocore.exceptions import ClientError   # ← ADD THIS LINE


AMI_MAP = {
    "ubuntu": {
        "ap-south-1":    "ami-0f58b397bc5c1f2e8",
        "us-east-1":     "ami-0c7217cdde317cfec",
        "us-west-2":     "ami-03c983f9003cb9cd1",
        "eu-west-1":     "ami-0905a3c97561e0b69",
        "ap-southeast-1":"ami-0fa377108253bf620",
    },
    "amazon-linux": {
        "ap-south-1":    "ami-0f5ee92e2d63afc18",
        "us-east-1":     "ami-0c101f26f147fa7fd",
        "us-west-2":     "ami-0eb9f45f1e91e8ece",
        "eu-west-1":     "ami-0b9fd8b55a6e3c9d5",
        "ap-southeast-1":"ami-04c913012f8977029",
    },
    "amazon-linux-2": {   # alias
        "ap-south-1":    "ami-0f5ee92e2d63afc18",
        "us-east-1":     "ami-0c101f26f147fa7fd",
        "us-west-2":     "ami-0eb9f45f1e91e8ece",
        "eu-west-1":     "ami-0b9fd8b55a6e3c9d5",
        "ap-southeast-1":"ami-04c913012f8977029",
    },
    "debian": {
        "ap-south-1":    "ami-0376129347a538951",
        "us-east-1":     "ami-064519b8c76274859",
        "us-west-2":     "ami-0d53d72369335a9d6",
        "eu-west-1":     "ami-0905a3c97561e0b69",
        "ap-southeast-1":"ami-0fa377108253bf620",
    },
    "windows": {
        "ap-south-1":    "ami-0aef57767f5404a3c",
        "us-east-1":     "ami-0f9c44e98edf38a2b",
        "us-west-2":     "ami-0a2363a9cff180a64",
        "eu-west-1":     "ami-0b9d2c77e3d5db9f8",
        "ap-southeast-1":"ami-0abcdef1234567890",
    },
}

# Normalize user-typed OS strings to AMI_MAP keys
OS_ALIASES = {
    "amazon linux":   "amazon-linux",
    "amazonlinux":    "amazon-linux",
    "amazon linux 2": "amazon-linux-2",
    "al2":            "amazon-linux-2",
    "win":            "windows",
    "win server":     "windows",
    "windows server": "windows",
    "deb":            "debian",
    "ubuntu 22":      "ubuntu",
    "ubuntu 20":      "ubuntu",
}

DEFAULT_AMI = AMI_MAP["ubuntu"]["ap-south-1"]

SSM_PATHS = {
    "ubuntu": "/aws/service/canonical/ubuntu/server/22.04/1.0/lf/amd64/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-latest",
    "amazon-linux": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
    "amazon-linux-2": "/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2",
    "debian": "/aws/service/debian/release/12/latest/amd64",
    "windows": "/aws/service/ami-windows-latest/Windows_Server-2022-English-Full-Base",
}

def get_ami(os_type: str, region: str, aws_creds: dict) -> str:
    raw    = (os_type or "ubuntu").lower().strip()
    os_key = OS_ALIASES.get(raw, raw.replace(" ", "-"))
    if os_key not in SSM_PATHS and os_key not in AMI_MAP:
        os_key = "ubuntu"
        
    # Attempt to dynamically fetch the latest valid AMI ID from SSM
    try:
        ssm = boto3.client(
            "ssm",
            region_name=region,
            aws_access_key_id=aws_creds.get("access_key"),
            aws_secret_access_key=aws_creds.get("secret_key")
        )
        response = ssm.get_parameter(Name=SSM_PATHS[os_key])
        return response["Parameter"]["Value"]
    except Exception:
        # Fallback to hardcoded map if dynamic fetch fails (e.g., missing IAM permissions for SSM)
        return AMI_MAP.get(os_key, AMI_MAP["ubuntu"]).get(region, DEFAULT_AMI)

def build_security_group_rules(ports: list) -> list:
    """Generate inbound rules from port list."""
    ports = ports or [22, 80]
    rules = []
    for port in ports:
        rules.append({
            "IpProtocol": "tcp",
            "FromPort": port,
            "ToPort": port,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": f"Auto-opened port {port}"}],
        })
    return rules


def _set_pem_permissions(pem_path: str):
    """
    Sets secure permissions on the .pem file.
    Windows: Uses icacls to remove inheritance and grant owner read-only.
    POSIX: Uses os.chmod 400.
    """
    if os.name == 'nt':
        import subprocess
        import getpass
        try:
            username = getpass.getuser()
            abs_path = os.path.abspath(pem_path)
            # 1. Disable inheritance and remove all existing permissions
            subprocess.run(["icacls", abs_path, "/inheritance:r"], check=True, capture_output=True)
            # 2. Grant explicit READ access to current user
            subprocess.run(["icacls", abs_path, "/grant:r", f"{username}:(R)"], check=True, capture_output=True)
        except Exception as e:
            print(f"⚠️ Warning: Failed to set Windows permissions via icacls: {e}")
    else:
        try:
            os.chmod(pem_path, 0o400)
        except Exception as e:
            print(f"⚠️ Warning: Failed to set POSIX permissions: {e}")


def _deploy_single_ec2(params: dict, aws_creds: dict, index: int = 1, total: int = 1) -> dict:
    region        = params.get("region") or aws_creds.get("region") or "ap-south-1"
    instance_type = params.get("instance_type") or "t2.micro"
    os_type       = params.get("os") or "ubuntu"
    name_tag      = params.get("name_tag") or f"AICloudAgent-{index}"
    ports         = params.get("ports") or [22, 80]
    key_pair_name = params.get("key_pair")

    try:
        ec2_resource = boto3.resource(
            "ec2",
            region_name=region,
            aws_access_key_id=aws_creds.get("access_key"),
            aws_secret_access_key=aws_creds.get("secret_key"),
        )
        ec2_client = ec2_resource.meta.client

        # 1. Create a dedicated Security Group
        sg_name = f"aicloud-{name_tag}-sg"
        try:
            sg = ec2_client.create_security_group(
                GroupName=sg_name,
                Description=f"Auto-created by AI Cloud Agent for {name_tag}",
            )
            sg_id = sg["GroupId"]
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=build_security_group_rules(ports),
            )
        except ClientError as e:
            if "InvalidGroup.Duplicate" in str(e):
                existing = ec2_client.describe_security_groups(GroupNames=[sg_name])
                sg_id = existing["SecurityGroups"][0]["GroupId"]
            else:
                raise e

        # 1.5 Auto-generate SSH KeyPair if needed with unique name
        if not key_pair_name:
            # Add timestamp to name for uniqueness
            key_pair_name = f"{name_tag}-{int(time.time())}"
        
        # Folder for keys
        keys_dir = os.path.join(os.getcwd(), "deployments", "keys")
        os.makedirs(keys_dir, exist_ok=True)
        
        pem_filename = f"{key_pair_name}.pem"
        pem_path = os.path.abspath(os.path.join(keys_dir, pem_filename))
        
        try:
            key = ec2_client.create_key_pair(KeyName=key_pair_name)
            with open(pem_path, "w") as f:
                f.write(key["KeyMaterial"])
            _set_pem_permissions(pem_path)
        except ClientError as e:
            # If key already exists in AWS somehow, we might not get private material
            if "InvalidKeyPair.Duplicate" in str(e):
                pass 
            else:
                raise e

        # 2. Build launch kwargs
        ami_id = get_ami(os_type, region, aws_creds)
        tags = [
            {"Key": "Name",         "Value": name_tag},
            {"Key": "CreatedBy",    "Value": "AICloudAgent"},
        ]
        if params.get("auto_teardown"):
            tags.append({"Key": "AutoTeardown", "Value": "24h"})
            
        launch_kwargs = {
            "ImageId":        ami_id,
            "InstanceType":   instance_type,
            "MinCount":       1,
            "MaxCount":       1,
            "SecurityGroupIds": [sg_id],
            "TagSpecifications": [{
                "ResourceType": "instance",
                "Tags": tags,
            }],
        }
        if key_pair_name:
            launch_kwargs["KeyName"] = key_pair_name

        # 3. Launch the instance
        instances = ec2_resource.create_instances(**launch_kwargs)
        instance = instances[0]
        instance_id = instance.id

        # 4. Wait for running
        # This is critical for public_ip retrieval as requested
        instance.wait_until_running()
        instance.reload()

        # 5. Get public IP
        public_ip = instance.public_ip_address or "N/A"
        # Diagnostic print for logs
        print(f"DEBUG: Instance {instance_id} state={instance.state['Name']} IP={public_ip}")

        # 6. Optional: Post-Install Commands via Paramiko
        ssh_output = ""
        cmds = params.get("post_install_commands")
        if cmds and public_ip != "N/A" and pem_path and os.path.exists(pem_path):
            try:
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Determine SSH user
                ssh_user = "ubuntu"
                if "amazon" in os_type.lower() or "linux" in os_type.lower(): ssh_user = "ec2-user"
                elif "debian" in os_type.lower(): ssh_user = "admin"
                
                # Poll for up to 60s
                success = False
                for _ in range(12):
                    try:
                        ssh.connect(hostname=public_ip, username=ssh_user, key_filename=pem_path, timeout=5)
                        success = True
                        break
                    except Exception:
                        time.sleep(5)
                        
                if success:
                    run_list = cmds if isinstance(cmds, list) else [cmds]
                    ssh_output += "\n\n**Post-Install Automations:**\n```bash\n"
                    # wait a little explicitly since apt-get locks can exist immediately after boot
                    time.sleep(5) 
                    for cmd in run_list:
                        stdin, stdout, stderr = ssh.exec_command(cmd)
                        out = stdout.read().decode('utf-8').strip()
                        err = stderr.read().decode('utf-8').strip()
                        ssh_output += f"$ {cmd}\n"
                        if out: ssh_output += f"{out}\n"
                        if err: ssh_output += f"{err}\n"
                    ssh_output += "```\n"
                    ssh.close()
                else:
                    ssh_output = "\n*(SSH connection timeout. Please run manually.)*"
            except Exception as e:
                ssh_output = f"\n*(SSH execution error: {str(e)})*"

        return {
            "success":     True,
            "instance_id": instance_id,
            "public_ip":   public_ip,
            "name_tag":    name_tag,
            "os":          os_type,
            "instance_type": instance_type,  
            "ports":       ports,
            "ssh_log":     ssh_output,
            "pem_filename": pem_filename if 'pem_filename' in locals() else None
        }

    except Exception:
        return {
            "success":  False,
            "name_tag": name_tag,
            "error":    traceback.format_exc(),
        }


def deploy_ec2(params: dict, aws_creds: dict) -> dict:
    """
    Executes EC2 deployment(s).
    - If params['servers'] is a populated list: each server gets its OWN config
    - If not: all instances clone the base params
    """
    servers = params.get("servers")
    count   = int(params.get("count") or (len(servers) if servers else 1))
    region  = params.get("region") or aws_creds.get("region") or "ap-south-1"

    results = []
    for i in range(count):
        # Pick per-server config if available, else fall back to base params
        if servers and isinstance(servers, list) and i < len(servers):
            server_params = dict(servers[i])
            # Inherit region and key_pair from base if not set per-server
            server_params.setdefault("region",   region)
            server_params.setdefault("key_pair", params.get("key_pair"))
            server_params.setdefault("ports",    params.get("ports") or [22, 80])
        else:
            server_params = dict(params)

        results.append(_deploy_single_ec2(server_params, aws_creds, index=i+1, total=count))

    successes = [r for r in results if r["success"]]
    failures  = [r for r in results if not r["success"]]
    lines     = []

    if successes:
        lines.append(f"✅ **{len(successes)}/{count} EC2 Instance(s) Deployed Successfully!**\n")
        lines.append("| # | Name | Instance ID | Public IP | OS | Type | SSH |")
        lines.append("|---|---|---|---|---|---|---|")
        for idx, r in enumerate(successes, 1):
            ssh_user = "ubuntu"
            if "amazon" in r.get("os", "ubuntu").lower() or "linux" in r.get("os", "ubuntu").lower(): ssh_user = "ec2-user"
            
            # Use deployments/keys/ path
            pem_name = r.get("pem_filename") or "aicloud-agent-key.pem"
            pem_rel_path = f"deployments/keys/{pem_name}"
            ssh = f"`ssh -i \"{pem_rel_path}\" {ssh_user}@{r['public_ip']}`" if r["public_ip"] != "N/A" else "N/A"
            
            lines.append(
                f"| {idx} | `{r['name_tag']}` | `{r['instance_id']}` | `{r['public_ip']}` "
                f"| `{r.get('os','ubuntu')}` | `{r.get('instance_type','t2.micro')}` | {ssh} |"
            )
            
        for r in successes:
            if r.get("ssh_log"):
                lines.append(f"\n**[ {r['name_tag']} ]** {r['ssh_log']}")

        if params.get("auto_teardown"):
            lines.append("⏰ **All instances securely tagged for auto-teardown in 24 hours.**")

    if failures:
        lines.append(f"\n❌ **{len(failures)} instance(s) failed:**")
        for r in failures:
            lines.append(f"\n**{r['name_tag']}**\n```\n{r['error']}\n```")

    return {
        "success": len(successes) > 0,
        "message": "\n".join(lines),
    }


def deploy_s3(params: dict, aws_creds: dict):
    """
    params: {
        'bucket_name': str,
        'region': str,
        'public_access': bool,
        'versioning': bool
    }
    """
    region = params.get("region", "ap-south-1")
    bucket = params["bucket_name"].lower()
    
    try:
        s3 = boto3.client(
            's3', 
            region_name=region,
            aws_access_key_id=aws_creds.get("access_key"),
            aws_secret_access_key=aws_creds.get("secret_key")
        )
        
        # Create bucket (us-east-1 does not tolerate LocationConstraint)
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
            
        # Wait for bucket to propagate to resolve NoSuchBucket issues
        waiter = s3.get_waiter('bucket_exists')
        waiter.wait(Bucket=bucket)
        time.sleep(2) # Extra buffer for global propagation
            
        # Configure Public Access Block
        if params.get("public_access"):
            s3.put_public_access_block(
                Bucket=bucket,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': False,
                    'IgnorePublicAcls': False,
                    'BlockPublicPolicy': False,
                    'RestrictPublicBuckets': False
                }
            )
        else:
            s3.put_public_access_block(
                Bucket=bucket,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )
            
        # Configure Versioning
        if params.get("versioning"):
            s3.put_bucket_versioning(
                Bucket=bucket,
                VersioningConfiguration={'Status': 'Enabled'}
            )
            
        return {"status": "success", "message": f"✅ **Successfully created S3 Bucket!**\n\n**Bucket Name:** `{bucket}`\n**Region:** `{region}`\n**Public Access:** `{'Enabled' if params.get('public_access') else 'Blocked'}`\n**Versioning:** `{'Enabled' if params.get('versioning') else 'Disabled'}`"}
        
    except ClientError as e:
        return {"status": "error", "message": f"❌ S3 Deployment Failed:\n\n```text\n{str(e)}\n```"}


def destroy_aws_resource(params: dict, aws_creds: dict):
    identifier = params.get("resource_identifier", "")
    region = params.get("region") or aws_creds.get("region", "ap-south-1")
    
    ec2 = boto3.client(
        "ec2",
        region_name=region,
        aws_access_key_id=aws_creds.get("access_key"),
        aws_secret_access_key=aws_creds.get("secret_key"),
    )
    
    def _get_instances_for_id(ec2_client, id_val: str):
        id_val = id_val.strip().lower()
        if id_val == "all":
            resp = ec2_client.describe_instances(
                Filters=[{"Name": "tag:CreatedBy", "Values": ["AICloudAgent"]}]
            )
        elif id_val.startswith("i-"):
            resp = ec2_client.describe_instances(InstanceIds=[id_val])
        else:
            resp = ec2_client.describe_instances(
                Filters=[{"Name": "tag:Name", "Values": [id_val]}]
            )
        result = []
        for r in resp.get("Reservations", []):
            for i in r.get("Instances", []):
                if i.get("State", {}).get("Name") not in ["terminated", "shutting-down"]:
                    result.append(i["InstanceId"])
        return result
    
    try:
        to_terminate = []
        if isinstance(identifier, list):
            for item in identifier:
                to_terminate.extend(_get_instances_for_id(ec2, item))
        else:
            to_terminate.extend(_get_instances_for_id(ec2, str(identifier)))
        
        # Deduplicate
        to_terminate = list(set(to_terminate))
                    
        if not to_terminate:
            return {"status": "success", "message": f"🤷 Could not find any active agent-deployed instances matching `{identifier}`. They may already be terminated."}
            
        ec2.terminate_instances(InstanceIds=to_terminate)
        
        md = f"✅ **Successfully initiated teardown for {len(to_terminate)} instance(s)!**\n\n"
        for i in to_terminate:
            md += f"- `{i}`\n"
        return {"status": "success", "message": md}
        
    except ClientError as e:
        return {"status": "error", "message": f"❌ Teardown Failed:\n\n```text\n{str(e)}\n```"}

def deploy_vpc(params: dict, aws_creds: dict):
    region = params.get("region", "ap-south-1")
    cidr_block = params.get("cidr_block", "10.0.0.0/16")
    subnet_count = int(params.get("subnet_count", 2))
    vpc_name = params.get("vpc_name", "AICloudAgent-VPC")
    
    try:
        ec2 = boto3.client(
            "ec2",
            region_name=region,
            aws_access_key_id=aws_creds.get("access_key"),
            aws_secret_access_key=aws_creds.get("secret_key"),
        )
        
        # 1. Create VPC
        vpc_res = ec2.create_vpc(CidrBlock=cidr_block)
        vpc_id = vpc_res["Vpc"]["VpcId"]
        
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
        
        ec2.create_tags(Resources=[vpc_id], Tags=[
            {"Key": "Name", "Value": vpc_name},
            {"Key": "CreatedBy", "Value": "AICloudAgent"}
        ])
        
        # 2. Create IGW
        igw_res = ec2.create_internet_gateway()
        igw_id = igw_res["InternetGateway"]["InternetGatewayId"]
        ec2.attach_internet_gateway(VpcId=vpc_id, InternetGatewayId=igw_id)
        ec2.create_tags(Resources=[igw_id], Tags=[{"Key": "Name", "Value": "AICloudAgent-IGW"}])
        
        # 3. Create Public Route Table
        rt_res = ec2.create_route_table(VpcId=vpc_id)
        rt_id = rt_res["RouteTable"]["RouteTableId"]
        ec2.create_route(RouteTableId=rt_id, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw_id)
        ec2.create_tags(Resources=[rt_id], Tags=[{"Key": "Name", "Value": "AICloudAgent-Public-RT"}])
        
        # 4. Create Subnets using ipaddress
        az_res = ec2.describe_availability_zones()
        azs = [az["ZoneName"] for az in az_res["AvailabilityZones"] if az["State"] == "available"]
        
        network = ipaddress.ip_network(cidr_block)
        prefix = network.prefixlen
        # Shift /16 -> /24 natively, or dynamically split space
        new_prefix = prefix + 8 if prefix <= 16 else prefix + 1 
        if new_prefix > 28: new_prefix = 28
        
        subnets_iter = network.subnets(new_prefix=new_prefix)
        created_subnets = []
        
        for i in range(subnet_count):
            sub_cidr = str(next(subnets_iter))
            az = azs[i % len(azs)]
            
            sub_res = ec2.create_subnet(VpcId=vpc_id, CidrBlock=sub_cidr, AvailabilityZone=az)
            sub_id = sub_res["Subnet"]["SubnetId"]
            
            # Map to Public RT as per User plan overrides
            ec2.associate_route_table(SubnetId=sub_id, RouteTableId=rt_id)
            ec2.modify_subnet_attribute(SubnetId=sub_id, MapPublicIpOnLaunch={'Value': True})
            
            ec2.create_tags(Resources=[sub_id], Tags=[
                {"Key": "Name", "Value": f"AICloudAgent-Public-Subnet-{i+1}"},
                {"Key": "CreatedBy", "Value": "AICloudAgent"}
            ])
            created_subnets.append({"id": sub_id, "cidr": sub_cidr, "az": az})
            
        md = f"✅ **VPC `{vpc_name}` Deployed Successfully!**\n\n"
        md += f"**VPC ID:** `{vpc_id}` (CIDR: `{cidr_block}`)\n"
        md += f"**VPC Name:** `{vpc_name}`\n"
        md += f"**Region:** `{region}`\n"
        md += f"**Internet Gateway:** `{igw_id}` \u2705 Attached\n\n"
        md += f"### Provisioned Public Subnets (all have public IP auto-assignment):\n"
        for s in created_subnets:
            md += f"- `{s['id']}` - **{s['cidr']}** (`{s['az']}`)\n"
            
        return {"status": "success", "message": md}
        
    except ClientError as e:
        return {"status": "error", "message": f"❌ VPC Deployment Failed:\n\n```text\n{str(e)}\n```"}
    
def deploy_docker_single(params: dict, aws_creds: dict) -> dict:
    """
    Deploys a single Docker container on a new EC2 instance.
    params: {image, tag, port, env_vars, region, instance_type}
    """
    region        = params.get("region") or aws_creds.get("region") or "ap-south-1"
    image         = params.get("image") or "nginx"
    tag           = params.get("tag") or "latest"
    port          = int(params.get("port") or 80)
    env_vars      = params.get("env_vars") or []
    instance_type = params.get("instance_type") or "t2.micro"
    name_tag      = params.get("name_tag") or f"docker-{image.replace('/', '-')}"

    # Build the docker run command
    env_flags = " ".join([f"-e {e}" for e in env_vars]) if env_vars else ""
    docker_run_cmd = f"docker run -d -p {port}:{port} {env_flags} {image}:{tag}"

    # Post-install: install docker then run container
    post_cmds = [
        "sudo apt-get update -y",
        "sudo apt-get install -y docker.io",
        "sudo systemctl start docker",
        "sudo systemctl enable docker",
        f"sudo {docker_run_cmd}",
    ]

    # Reuse EC2 deploy with post_install_commands
    ec2_params = {
        "os":                   "ubuntu",
        "instance_type":        instance_type,
        "region":               region,
        "ports":                [22, port],
        "name_tag":             name_tag,
        "post_install_commands": post_cmds,
    }

    result = _deploy_single_ec2(ec2_params, aws_creds)

    if result["success"]:
        public_ip = result["public_ip"]
        result["message"] = (
            f"✅ **Docker Container Deployed!**\n\n"
            f"| Field | Value |\n|---|---|\n"
            f"| 🐳 Image | `{image}:{tag}` |\n"
            f"| 🖥️ Instance | `{result['instance_id']}` |\n"
            f"| 🌐 Public IP | `{public_ip}` |\n"
            f"| 🔓 Port | `{port}` |\n"
            f"| 🌍 URL | `http://{public_ip}:{port}` |\n\n"
            f"{result.get('ssh_log', '')}"
        )
    return result

def deploy_docker_compose(params: dict, aws_creds: dict) -> dict:
    """
    Deploys a multi-container app using docker-compose on a new EC2 instance.
    params: {app_image, db_type, app_port, db_version, region, instance_type}
    """
    region      = params.get("region") or aws_creds.get("region") or "ap-south-1"
    app_image   = params.get("app_image") or "nginx"
    db_type     = params.get("db_type") or "postgres"
    app_port    = int(params.get("app_port") or 80)
    db_version  = params.get("db_version") or "latest"
    name_tag    = params.get("name_tag") or f"compose-{app_image.replace('/', '-')}"

    # Generate docker-compose.yml content
    compose_content = f"""version: '3.8'
services:
  app:
    image: {app_image}
    ports:
      - "{app_port}:{app_port}"
    depends_on:
      - db
    restart: always
  db:
    image: {db_type}:{db_version}
    restart: always
    environment:
      - POSTGRES_PASSWORD=agentpass
      - MYSQL_ROOT_PASSWORD=agentpass
"""

    # Escape for shell echo
    compose_escaped = compose_content.replace("'", "'\"'\"'")

    post_cmds = [
        "sudo apt-get update -y",
        "sudo apt-get install -y docker.io docker-compose",
        "sudo systemctl start docker",
        "sudo systemctl enable docker",
        "mkdir -p ~/app",
        f"echo '{compose_escaped}' > ~/app/docker-compose.yml",
        "cd ~/app && sudo docker-compose up -d",
    ]

    ec2_params = {
        "os":                    "ubuntu",
        "instance_type":         params.get("instance_type") or "t2.small",
        "region":                region,
        "ports":                 [22, app_port],
        "name_tag":              name_tag,
        "post_install_commands": post_cmds,
    }

    result = _deploy_single_ec2(ec2_params, aws_creds)

    if result["success"]:
        public_ip = result["public_ip"]
        result["message"] = (
            f"✅ **Docker Compose Stack Deployed!**\n\n"
            f"| Field | Value |\n|---|---|\n"
            f"| 📦 App | `{app_image}` |\n"
            f"| 🗄️ DB | `{db_type}:{db_version}` |\n"
            f"| 🖥️ Instance | `{result['instance_id']}` |\n"
            f"| 🌐 Public IP | `{public_ip}` |\n"
            f"| 🌍 URL | `http://{public_ip}:{app_port}` |\n\n"
            f"{result.get('ssh_log', '')}"
        )
    return result


def upload_to_s3(file_obj, bucket_name, region, aws_creds) -> dict:
    """Uploads a file object to a specific S3 bucket and returns a presigned URL."""
    try:
        s3 = boto3.client(
            's3', 
            region_name=region,
            aws_access_key_id=aws_creds.get("access_key"),
            aws_secret_access_key=aws_creds.get("secret_key")
        )
        s3.upload_fileobj(file_obj, bucket_name, file_obj.name)
        
        # Generate Presigned URL (1 hour)
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': file_obj.name},
            ExpiresIn=3600
        )
        
        return {
            "success": True, 
            "message": f"Successfully uploaded `{file_obj.name}`.",
            "file_name": file_obj.name,
            "bucket": bucket_name,
            "uri": f"s3://{bucket_name}/{file_obj.name}",
            "url": presigned_url
        }
    except Exception as e:
        return {"success": False, "message": f"Error uploading to S3: {str(e)}"}


def list_s3_files(bucket_name, region, aws_creds) -> list:
    """Lists files in an S3 bucket and generates presigned URLs."""
    try:
        s3 = boto3.client(
            's3', 
            region_name=region,
            aws_access_key_id=aws_creds.get("access_key"),
            aws_secret_access_key=aws_creds.get("secret_key")
        )
        response = s3.list_objects_v2(Bucket=bucket_name)
        
        files = []
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': key},
                    ExpiresIn=3600
                )
                files.append({
                    "name": key,
                    "uri": f"s3://{bucket_name}/{key}",
                    "url": url,
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].strftime('%Y-%m-%d %H:%M')
                })
        return files
    except Exception as e:
        print(f"Error listing S3 files: {e}")
        return []
