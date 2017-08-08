#!/usr/bin/env python

import argparse
import json
import os
import socket
import subprocess
import sys


"""
symp -k volume create --size 1000 s3-vol -c id -f json |
   python -c "import sys,json; print json.load(sys.stdin)['id']" | xargs -I{} mancala volumes attach-to-host {} `hostname` --json |
   python -c "import sys,json; print json.load(sys.stdin)['attachments'][0]['mountpoint']" |
   xargs -I{} bash -c "mkdir -p /mnt/s3; mkfs -t xfs {}; mount {} /mnt/s3/; mkdir -p /mnt/s3/meta; mkdir -p /mnt/s3/s3; echo {}"
   xargs -I{} consul kv put s3-scality/v1/s3-volume '{"format": "v1", "volume-uuid": "{}"}'

consul kv get s3-scality/v1/s3-volume |
   python -c "import sys,json; print json.load(sys.stdin)['volume-uuid']" |
   xargs -I{} mancala volumes attach-to-host {} `hostname` --json |
   python -c "import sys,json; print json.load(sys.stdin)['attachments'][0]['mountpoint']" |
   xargs -I{} bash -c "mkdir -p /mnt/s3; mkfs -t ext4 {}; mount {} /mnt/s3/; mkdir -p /mnt/s3/meta; mkdir -p /mnt/s3/s3"

"""
S3_KV_PATH = "s3-scality/v1/s3-volume"
S3_MOUNT_DIR = "/mnt/s3"
S3_DATA_PATH = os.path.join(S3_MOUNT_DIR,"data")
S3_METADATA_PATH = os.path.join(S3_MOUNT_DIR,"meta")

def _detach_volume_from_host(volume_uuid, hostname):
    print "Detaching volume %s from previously attached host %s" % (volume_uuid, hostname)
    try:
        output = subprocess.check_output(["mancala", "volumes", "detach-from-host", volume_uuid,
        hostname, "--json"]).strip()
        print "Detached from host %s" % hostname
    except Exception as e:
        print "Failed dettach volume %s from host %s (%s)" % (volume_uuid, hostname, e)
        raise


def _umount_dir_from_host(dir_name):
    if subprocess.call(["mountpoint", "-q", dir_name]):
        print "%s is not mounted" % dir_name
        return 0

    print "Unmounting %s" % dir_name
    try:
        output = subprocess.check_output(["umount", S3_MOUNT_DIR]).strip()
    except Exception as e:
        print "Failed unmount %s (%s)" % (dir_name,e)
        raise
    print "Succesfully unmounted %s" % dir_name
    return 0

def _detach_volume_from_all_hosts(volume_uuid):
    err = False
    try:
        output = subprocess.check_output(["mancala", "volumes", "get", volume_uuid, "--json"]).strip()
    except Exception as e:
        print "Failed attach get volume info (%s)" % e
        raise

    attachments = json.loads(output)['attachments']
    if not len(attachments):
        print "No attachments for %s" % volume_uuid
        return 0

    attached_hosts = attachments[0].get('hosts', [])

    if not len(attached_hosts):
        print "No hosts attachments"
        return 0
    print "Removing previous attachments. Just in case..."

    for hostname in attached_hosts:
        try:
            _detach_volume_from_host(volume_uuid, hostname)
        except Exception as e:
            err = True
    if err:
        raise

def _get_init_info():
    try:
        output = subprocess.check_output(["consul", "kv", "get", S3_KV_PATH]).strip()
    except subprocess.CalledProcessError:
        raise
    s3_init_info = json.loads(output)
    assert s3_init_info['format'] == 'v1'
    print "volume uuid: %s" % s3_init_info["volume-uuid"]
    return s3_init_info["volume-uuid"]

def pre_start():
    print "Pre start"
    try:
        volume_uuid = _get_init_info()
    except:
        print "S3 was not initialized. As a workaround, continue and let service initilization to block."
        return 0
    try:
        _umount_dir_from_host(S3_MOUNT_DIR)
    except:
        return 1
    try:
        _detach_volume_from_all_hosts(volume_uuid)
    except Exception:
        return 1

    print "Attaching to host %s..." % socket.gethostname()
    try:
        output = subprocess.check_output(["mancala", "volumes", "attach-to-host", volume_uuid,
        socket.gethostname(), "--json"]).strip()
    except Exception as e:
        print "Failed attach to host (%s)" % e
        return 1
    mountpoint = json.loads(output)['attachments'][0]['mountpoint']
    print 'mountpoint: %s' % mountpoint
    try:
        output = subprocess.check_output(["mount", mountpoint, S3_MOUNT_DIR]).strip()
        print "mkdir %s" % S3_DATA_PATH
        subprocess.call(["mkdir", "-p", S3_DATA_PATH])
        print "mkdir %s" % S3_METADATA_PATH
        subprocess.call(["mkdir", "-p", S3_METADATA_PATH])
    except Exception as e:
        print "Failed mount to host (%s)" % e
        return 1
    print subprocess.check_output(["tree", S3_MOUNT_DIR]).strip()
    return 0

def post_stop():
    err = 0
    print "Post stop"
    try:
        volume_uuid = _get_init_info()
    except:
        print "Could not find initialized info. Continue with the cleanup anyway!"
        volume_uuid = None
    try:
        _umount_dir_from_host(S3_MOUNT_DIR)
    except:
        err = 1
    if volume_uuid:
        try:
            _detach_volume_from_host(volume_uuid, socket.gethostname())
        except:
            err = 1
    return err

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    #parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False, help="print to screen instead of commenting in Jira")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pre", action="store_true", help='Pre start flow')
    group.add_argument("--post", action="store_true", help='Pre start flow')
    args = parser.parse_args()

    if args.pre:
        sys.exit(pre_start())
    else:
        sys.exit(post_stop())


"""

if [[ `consul kv get "$S3_KV_PATH" > /dev/null 2>&1; echo $?` -ne "0" ]]; then
    docker inspect -f {{.State.Running}} s3-scality.service.strato > /dev/null 2>&1;
else
    curl -s http://127.0.0.1:8800/_/healthcheck > /dev/null 2>&1;
fi
"""
