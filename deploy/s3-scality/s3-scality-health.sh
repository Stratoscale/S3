#!/bin/bash


S3_KV_PATH="s3-scality/v1/s3-volume"

if [[ `consul kv get "$S3_KV_PATH" > /dev/null 2>&1; echo $?` -ne "0" ]]; then
    docker inspect -f {{.State.Running}} s3-scality.service.strato > /dev/null 2>&1;
else
    curl -s http://127.0.0.1:8800/_/healthcheck > /dev/null 2>&1;
fi

