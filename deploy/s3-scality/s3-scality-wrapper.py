#!/usr/bin/env python

import argparse
import json
import logging
import os
import socket
import subprocess
import sys

from s3_manager_client import client
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
    return _cmapi.status.getNodeComponentStatus(hostname, cmapi_consts.NodeComponents.NODE_FENCING, default=False)


def _safe_detach_volume_from_host(hostname, volume_uuid):
    logging.info("Detaching volume %s from previously attached host %s" % (volume_uuid, hostname))
    try:
        is_fenced = _is_node_fenced(hostname)
    except Exception as e:
        logging.warning("Could not retrieve fenced state of host %s (%s). Assuming it's not" % (hostname, e))
        is_fenced = False

    detach_cmd = ["mancala", "volumes", "detach-from-host", volume_uuid, hostname, "--json"]
    if is_fenced:
        logging.warning("Host %s is fenced. Detaching forcefully" % (hostname))
        detach_cmd.append("--force")
    else:
        logging.info("Host %s is not fenced. Detaching gracefully" % (hostname))
    try:
        output = subprocess.check_output(detach_cmd).strip()
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


def _detach_volume_from_all_hosts(volume_uuid):
    err = False
    try:
        output = subprocess.check_output(["mancala", "volumes", "get", volume_uuid, "--json"]).strip()
    except Exception as e:
        logging.error("Failed to get volume %s info (%s)" % (volume_uuid, e))
        raise

    attachments = json.loads(output)['attachments']
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
            _safe_detach_volume_from_host(hostname, volume_uuid)
        except Exception as e:
            err = True
    if err:
        raise


def _get_init_info():
    s3_client = client.Client()
    init_info = s3_client.api.v2.object_stores.list()

    if len(init_info) == 0:
        return None
    assert len(init_info) == 1
    if init_info[0]['status'] != "Ready":
        logging.info('Init in progress (%s). Restarting' % init_info[0])
        raise
    volume_uuid = init_info[0]['mancala_volume_id']
    logging.info("volume uuid: %s" % volume_uuid)
    return volume_uuid


def pre_start():
    logging.info("Pre start enter")
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
        _detach_volume_from_all_hosts(volume_uuid)
    except Exception as e:
        logging.error("Failed to detach volume %s (%s). Exiting..." % (volume_uuid, e))
        return 1

    logging.info("Attaching to host %s..." % socket.gethostname())
    try:
        output = subprocess.check_output(["mancala", "volumes", "attach-to-host", volume_uuid, socket.gethostname(), "--json"]).strip()
    except Exception as e:
        logging.error("Failed attach to host (%s). Exiting..." % e)
        return 1
    mountpoint = json.loads(output)['attachments'][0]['mountpoint']
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
    try:
        volume_uuid = _get_init_info()
    except:
        logging.info("Could not find initialized info. Continue with the cleanup anyway!")
        volume_uuid = None
    try:
        _umount_dir_from_host(S3_MOUNT_DIR)
    except:
        err = 1
    if volume_uuid:
        try:
            _safe_detach_volume_from_host(socket.gethostname(), volume_uuid)
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
