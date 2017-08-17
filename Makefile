#-*- Makefile -*-

ifdef DEBUG
# Tests debug mode enabled (SKIPPER_INTERACTIVE must be set for this to work)
DEBUGGER=--debugger
MULTIPROCESS=
else
# Tests debug mode disabled
DEBUGGER=
MULTIPROCESS=-N 4
endif

# Service version based on git revision
VERSION=$(shell git rev-parse HEAD)

PWD=`pwd`
RPM_BUILD_ROOT ?= $(PWD)/build/rpmbuild

all: rpm

build:
	skipper build s3-scality
	docker tag s3-scality:$(VERSION) s3-scality:last_build

rpm: $(shell find deploy -type f)
	rpmbuild -bb -vv --define "_srcdir $(PWD)" --define "_topdir $(RPM_BUILD_ROOT)" deploy/s3-scality/s3-scality-deploy.spec

clean:
	rm -rf dist reports *.egg-info build logs .eggs
	find -name "*.pyc" -delete
	find -name "*~" -delete

push: build
	skipper push s3-scality

deploy: push
	skipper run deploy $(NORTHBOUND_IP) s3-scality $(VERSION) --image-name s3-scality

deploy_full: push rpm
	packager pack artifacts.yaml --auto-push
	skipper run deploy $(IP) s3-scality $(VERSION)_s3-scality_PACKED --image-name s3-scality
