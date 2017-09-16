#!/usr/bin/env python

import argparse
import json
import logging
import os
import socket
import subprocess
import sys

from melet_api_client import client as melet_client
from s3_manager_client import client
from strato_common import credentials as common_credentials
from strato_kv.clustermanagement import clustermanagementapi
import strato_kv.clustermanagement.consts as cmapi_consts

os.environ["STRATO_LOGS_DIRECTORY"] = "/var/log/stratoscale"
from strato_common.log import configurelogging  # NOQA
configurelogging.configureLogging("s3-scality")

S3_MOUNT_DIR = "/mnt/s3"
S3_DATA_PATH = os.path.join(S3_MOUNT_DIR, "data")
S3_METADATA_PATH = os.path.join(S3_MOUNT_DIR, "meta")


def _is_node_fenced(hostname):
    logging.info("Validating whether the host %s is fenced" % (hostname))
    _cmapi = clustermanagementapi.ClusterManagementAPI()
    return _cmapi.status.getNodeComponentStatus(hostname, cmapi_consts.NodeComponents.NODE_FENCING_BECAUSE_DISCONNECTED, default=False)


def _safe_detach_volume_from_host(melet, hostname, volume_uuid):
    logging.info("Detaching volume %s from previously attached host %s" % (volume_uuid, hostname))
    try:
        is_fenced = _is_node_fenced(hostname)
    except Exception as e:
        logging.warning("Could not retrieve fenced state of host %s (%s). Assuming it's not" % (hostname, e))
        is_fenced = False

    force = False
    if is_fenced:
        logging.warning("Host %s is fenced. Detaching forcefully" % (hostname))
        force = True
    else:
        logging.info("Host %s is not fenced. Detaching gracefully" % (hostname))
    try:
        melet.internal.v2.storage.volumes.detach_from_host(volume_uuid, hostname, force=force)
        logging.info("Detached from host %s" % hostname)
    except Exception as e:
        logging.error("Failed dettach volume %s from host %s (%s)" % (volume_uuid, hostname, e))
        raise


def _umount_dir_from_host(dir_name):
    if subprocess.call(["mountpoint", "-q", dir_name]):
        logging.info("%s is not mounted" % dir_name)
        return 0

    logging.info("Unmounting %s" % dir_name)
    try:
        subprocess.call(["sync"])
        output = subprocess.check_output(["umount", S3_MOUNT_DIR]).strip()
    except Exception as e:
        logging.error("Failed unmount %s (%s)" % (dir_name, e))
        raise
    logging.info("Succesfully unmounted %s" % dir_name)
    return 0


def _detach_volume_from_all_hosts(melet, volume_uuid):
    err = False
    try:
        output = melet.internal.v2.storage.volumes.get(volume_uuid)
    except Exception as e:
        logging.error("Failed to get volume %s info (%s)" % (volume_uuid, e))
        raise

    attachments = output['attachments']
    if not len(attachments):
        logging.info("No attachments for %s" % volume_uuid)
        return 0

    attached_hosts = attachments[0].get('hosts', [])

    if not len(attached_hosts):
        logging.info("No hosts attachments")
        return 0
    logging.info("Removing previous attachments. Just in case...")

    for hostname in attached_hosts:
        try:
            _safe_detach_volume_from_host(melet, hostname, volume_uuid)
        except Exception as e:
            err = True
    if err:
        raise


def _get_init_info(allowed_states=None):
    s3_client = client.Client()
    init_info = s3_client.api.v2.object_stores.list()

    if len(init_info) == 0:
        return None
    assert len(init_info) == 1

    if allowed_states is None:
        allowed_states = ["Ready"]

    if init_info[0]['status'] not in allowed_states:
        logging.info('Init in progress (%s). Restarting' % init_info[0])
        raise Exception('Init in progress (%s). Restarting' % init_info[0])

    volume_uuid = init_info[0]['mancala_volume_id']
    logging.info("volume uuid: %s" % volume_uuid)
    return volume_uuid


def pre_start():
    logging.info("Pre start enter")
    melet = melet_client.Client(headers=common_credentials.get_internal_headers(), timeout=200)
    try:
        volume_uuid = _get_init_info()
    except Exception as e:
        logging.error("Failed to get volume uuid (%s). Exiting..." % e)
        return 1
    try:
        _umount_dir_from_host(S3_MOUNT_DIR)
    except:
        logging.error("Failed to unmount from host (%s). Exiting..." % e)
        return 1
    if volume_uuid is None:
        logging.warning("S3 was not initialized. As a workaround, continue and let service initilization to block.")
        return 0
    try:
        _detach_volume_from_all_hosts(melet, volume_uuid)
    except Exception as e:
        logging.error("Failed to detach volume %s (%s). Exiting..." % (volume_uuid, e))
        return 1

    logging.info("Attaching to host %s..." % socket.gethostname())
    try:
        output = melet.internal.v2.storage.volumes.attach_to_host(volume_uuid, socket.gethostname())
    except Exception as e:
        logging.error("Failed attach to host (%s). Exiting..." % e)
        return 1
    mountpoint = output['attachments'][0]['mountpoint']
    logging.info('mountpoint: %s' % mountpoint)
    try:
        logging.info("mkdir -p %s" % S3_MOUNT_DIR)
        subprocess.call(["mkdir", "-p", S3_MOUNT_DIR])
        output = subprocess.check_output(["mount", mountpoint, S3_MOUNT_DIR]).strip()
        logging.info("mkdir -p %s" % S3_DATA_PATH)
        subprocess.call(["mkdir", "-p", S3_DATA_PATH])
        logging.info("mkdir -p %s" % S3_METADATA_PATH)
        subprocess.call(["mkdir", "-p", S3_METADATA_PATH])
    except Exception as e:
        logging.error("Failed mount to host (%s). Exiting..." % e)
        return 1
    logging.info("Pre start exit")
    return 0


def post_stop():
    err = 0
    logging.info("Post stop enter")
    melet = melet_client.Client(headers=common_credentials.get_internal_headers(), timeout=200)
    try:
        volume_uuid = _get_init_info(allowed_states=["Ready", "Deleting", "Error"])
    except:
        logging.info("Could not find initialized info. Continue with the cleanup anyway!")
        volume_uuid = None
    try:
        _umount_dir_from_host(S3_MOUNT_DIR)
    except:
        err = 1
    if volume_uuid:
        try:
            _safe_detach_volume_from_host(melet, socket.gethostname(), volume_uuid)
        except:
            err = 1
    logging.info("Post stop exit")
    return err


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pre", action="store_true", help='Pre start flow')
    group.add_argument("--post", action="store_true", help='Pre start flow')
    args = parser.parse_args()

    if args.pre:
        sys.exit(pre_start())
    else:
        sys.exit(post_stop())
