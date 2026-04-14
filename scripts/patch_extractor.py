import re

with open('agent/extractor.py', 'r') as f:
    content = f.read()

old = '    "VPC_SETUP": """Extract (null if not mentioned):\n- cidr_block, region, subnet_count (int), enable_nat_gateway (bool)\nRespond ONLY valid JSON.""",'
new = '    "VPC_SETUP": """Extract from the user message (null if not mentioned):\n- cidr_block: IP CIDR block e.g. \'10.0.0.0/16\' (string or null)\n- region: AWS region e.g. \'ap-south-1\' (string or null)\n- subnet_count: number of subnets requested (int or null)\n- enable_nat_gateway: true if user explicitly requests NAT or private subnets (bool or null)\n- vpc_name: custom VPC name if user specified (string or null)\nRespond ONLY valid JSON.""",'

if old in content:
    new_content = content.replace(old, new)
    with open('agent/extractor.py', 'w') as f:
        f.write(new_content)
    print('Done - replaced successfully')
else:
    print('NOT FOUND - printing surroundings:')
    idx = content.find('VPC_SETUP')
    print(repr(content[idx:idx+200]))
