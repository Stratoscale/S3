#!/bin/bash

S3_MANAGER_URL="http://s3-manager-api.service.strato:7540/api/v2/object-stores"

if [[ `curl -s "$S3_MANAGER_URL" | grep -qE 'Ready'; echo $?` -ne "0" ]]; then
    docker inspect -f {{.State.Running}} s3-scality.service.strato > /dev/null 2>&1;
else
    curl -s http://127.0.0.1:8800/_/healthcheck > /dev/null 2>&1;
fi

