import os
import sys

# Add the agent directory to the path so we can import executor
sys.path.append(os.getcwd())

from agent.executor import _set_pem_permissions

test_file = "test_permissions.pem"

# 1. Create a fake pem file
with open(test_file, "w") as f:
    f.write("-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY_DATA\n-----END RSA PRIVATE KEY-----")

print(f"Created {test_file}")

# 2. Run the logic
try:
    print("Applying permissions...")
    _set_pem_permissions(test_file)
    print("Success!")
except Exception as e:
    print(f"Error: {e}")

# 3. Check permissions (Windows-specific check)
if os.name == 'nt':
    import subprocess
    print("\nVerifying with icacls:")
    res = subprocess.run(["icacls", test_file], capture_output=True, text=True)
    print(res.stdout)

# Cleanup
# os.remove(test_file)
