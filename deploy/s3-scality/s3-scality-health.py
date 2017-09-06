#!/usr/bin/env python
import requests
import subprocess
import sys
from s3_manager_client import client

# Healthcheck flow:
# 1. If scality health is 200, check whether the service is registered
# 1.1 If not, return unhealthy - scality will be restarted and moved to the 'uninitialized mode'
# 1.2 If does, return 0
# 2. If scality health is not 200, check whether the service is registered
# 2.1 If not, just verify that the docker container is running
# 2.2 If does, return error

SCALITY_HEALTH = "http://127.0.0.1:8800/_/healthcheck"


def _is_s3_container_running():
    try:
        output = subprocess.check_output("docker inspect -f {{.State.Running}} s3-scality.service.strato".split(), stderr=subprocess.STDOUT).strip()
    except:
        output = "false"
    return 0 if "true" == output else 2

try:
    scality_health_response = requests.get(SCALITY_HEALTH)
except:
    scality_health_response = None

try:
    s3_client = client.Client()
    init_info = s3_client.api.v2.object_stores.list()
except:
    init_info = None

# scality not answering and s3-manager not answering
if scality_health_response is None and init_info is None:
    print ("scality_health_response == None and init_info == None:")
    sys.exit(_is_s3_container_running())

# scality not answering and s3-manager not initilizaed yet
if scality_health_response is None and (0 == len(init_info) or init_info[0]["status"] != "Ready"):
    print('scality_health_response == None and (0 == len(init_info) or init_info[0]["status"] != "Ready")')
    sys.exit(_is_s3_container_running())

# scality not answering and s3-manager initlaized - error
if scality_health_response is None and init_info[0]["status"] == "Ready":
    print('scality_health_response == None and init_info[0]["status"] == "Ready"')
    sys.exit(2)

# should not happen. Just in case
if scality_health_response is None:
    print('scality_health_response == None')
    sys.exit(2)

# scality healthy and s3-manager not answering
if scality_health_response.ok and init_info is None:
    print('scality_health_response.ok and init_info == None')
    sys.exit(0)

# In case of pool removal after initialization
if scality_health_response.ok and (0 == len(init_info) or init_info[0]["status"] != "Ready"):
    print('scality_health_response.ok and (0 == len(init_info) or init_info[0]["status"] != "Ready")')
    sys.exit(2)

if scality_health_response.ok and init_info[0]["status"] == "Ready":
    print ('scality_health_response.ok and init_info[0]["status"] == "Ready"')
    sys.exit(0)

# scality complains, and we passed all the above vaildations - just restart
if not scality_health_response.ok:
    print('not scality_health_response.ok')
    sys.exit(2)
