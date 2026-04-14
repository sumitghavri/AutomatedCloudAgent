import os
import time
import boto3
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv(override=True)

def run_daemon():
    print(f"[{datetime.now().isoformat()}] 🧹 Starting AI Cloud Agent Auto-Teardown Scan...")
    
    # In a full app, you might iterate across multiple regions.
    # We will use the default region or ap-south-1.
    region = os.environ.get("AWS_REGION", "ap-south-1")
    
    try:
        ec2 = boto3.client(
            "ec2",
            region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
        )
        
        # Find instances tagged with AutoTeardown
        instances = ec2.describe_instances(
            Filters=[
                {"Name": "tag:AutoTeardown", "Values": ["24h"]},
                {"Name": "instance-state-name", "Values": ["running", "stopped", "pending"]}
            ]
        )
        
        to_terminate = []
        now = datetime.now(timezone.utc)
        
        for r in instances.get("Reservations", []):
            for i in r.get("Instances", []):
                launch_time = i.get("LaunchTime")
                if not launch_time: continue
                
                # Calculate age
                age = now - launch_time
                if age > timedelta(hours=24):
                    to_terminate.append(i["InstanceId"])
                    name = "Unknown"
                    for t in i.get("Tags", []):
                        if t["Key"] == "Name":
                            name = t["Value"]
                    print(f"⚠️ Instance {i['InstanceId']} ({name}) is {age.total_seconds() / 3600:.1f} hours old. Terminating.")

        if to_terminate:
            ec2.terminate_instances(InstanceIds=to_terminate)
            print(f"✅ Successfully issued termination for {len(to_terminate)} expired instances.")
        else:
            print("✨ No expired instances found.")
            
    except Exception as e:
        print(f"❌ Error running teardown daemon: {str(e)}")

if __name__ == "__main__":
    while True:
        run_daemon()
        print("💤 Sleeping for 1 hour before next scan...\n")
        time.sleep(3600)  # run every 1 hour
