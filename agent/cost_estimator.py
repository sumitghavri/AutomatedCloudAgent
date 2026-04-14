"""
agent/cost_estimator.py
-----------------------
Professional AWS & Docker Cost Estimator with Infrastructure vs Service breakdown.
Uses static lookup tables for instant response times.
"""

# AWS Pricing Data (Approximate Hourly Rates)
# Regions: ap-south-1 (Mumbai), us-east-1 (N. Virginia)
AWS_PRICING = {
    "EC2": {
        "t2.micro":  {"linux": 0.0116, "windows": 0.0162},
        "t3.micro":  {"linux": 0.0104, "windows": 0.0150},
        "t3.small":  {"linux": 0.0208, "windows": 0.0300},
        "t3.medium": {"linux": 0.0416, "windows": 0.0600},
        "m5.large":  {"linux": 0.0960, "windows": 0.1880},
    },
    "S3": {
        "storage_gb": 0.023,  # per GB-Month
        "request_1k": 0.005,  # per 1000 PUT/POST
    },
    "VPC": {
        "vpc": 0.0,
        "nat_gateway": 0.045, # per hour
    }
}

# Service/Docker Overhead Data
SERVICE_PRICING = {
    "DOCKER_EC2": {
        "registry_storage": 0.0001, # Simulating ECR GB/hr
        "orchestration": 0.0,       # Self-managed on EC2
    },
    "FARGATE": {
        "vcpu_hr": 0.04048,
        "gb_hr": 0.004445,
    },
    "MANAGEMENT_FEE": 0.01, # Flat simulation fee for "Registry Management"
}

def calculate_deployment_cost(intent: str, params: dict) -> dict:
    """
    Returns a structured cost breakdown based on deployment parameters.
    Returns: { "infra": float, "service": float, "total": float, "monthly": float, "currency": "USD" }
    """
    infra_hourly = 0.0
    service_hourly = 0.0
    
    region = params.get("region", "ap-south-1") # Note: Region multiplier could be added here
    
    # -----------------------------------------------------------------------
    # EC2 Calculations
    # -----------------------------------------------------------------------
    if intent == "EC2_DEPLOY":
        count = int(params.get("count") or 1)
        inst_type = params.get("instance_type", "t2.micro")
        os_type = params.get("os", "linux").lower()
        if "windows" in os_type:
            os_key = "windows"
        else:
            os_key = "linux"
            
        rate = AWS_PRICING["EC2"].get(inst_type, AWS_PRICING["EC2"]["t2.micro"]).get(os_key, 0.01)
        infra_hourly = rate * count
        
    # -----------------------------------------------------------------------
    # S3 Calculations
    # -----------------------------------------------------------------------
    elif intent == "S3_CREATE":
        # S3 is mostly usage based, but we can provide a base storage estimate
        # Assume a default 5GB starter footprint
        infra_hourly = (AWS_PRICING["S3"]["storage_gb"] * 5) / 730 # Monthly to hourly
        service_hourly = 0.0002 # Basic request overhead
        
    # -----------------------------------------------------------------------
    # VPC Calculations
    # -----------------------------------------------------------------------
    elif intent == "VPC_SETUP":
        infra_hourly = 0.0
        if params.get("enable_nat_gateway"):
            infra_hourly = AWS_PRICING["VPC"]["nat_gateway"]
            
    # -----------------------------------------------------------------------
    # Docker Synergy Calculations (Docker on EC2)
    # -----------------------------------------------------------------------
    elif intent in ["DOCKER_SINGLE", "DOCKER_COMPOSE"]:
        # Usually Docker runs on a VM (Infrastructure) + has Service overhead
        inst_type = params.get("instance_type", "t3.micro")
        infra_hourly = AWS_PRICING["EC2"].get(inst_type, AWS_PRICING["EC2"]["t3.micro"]).get("linux")
        
        # Service overhead (ECR storage, Docker management simulation)
        service_hourly = SERVICE_PRICING["DOCKER_EC2"]["registry_storage"] + SERVICE_PRICING["MANAGEMENT_FEE"]

    total_hourly = infra_hourly + service_hourly
    total_monthly = total_hourly * 730 # Standard cloud month hours
    
    return {
        "infra": round(infra_hourly, 4),
        "service": round(service_hourly, 4),
        "total": round(total_hourly, 4),
        "monthly": round(total_monthly, 2),
        "currency": "USD"
    }
