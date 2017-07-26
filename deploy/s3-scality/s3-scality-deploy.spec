%define longhash %(git log | head -1 | awk '{print $2}')
%define shorthash %(echo %{longhash} | dd bs=1 count=12)

Name:    s3-scality-deploy
Version: 1.0
Release: 1.strato.%{shorthash}
Summary: s3-scality service deploy
Packager: Stratoscale Ltd
Vendor: Stratoscale Ltd
URL: http://www.stratoscale.com
#Source0: THIS_GIT_COMMIT
License: Strato

%define __strip /bin/true
%define __spec_install_port /usr/lib/rpm/brp-compress

%description
s3-scality service deployment

%build
cp %{_srcdir}/deploy/s3-scality/s3-scality.service .
cp %{_srcdir}/deploy/s3-scality/s3-scality.yml .
cp %{_srcdir}/deploy/s3-scality/s3-scality-monitor.service .
cp %{_srcdir}/deploy/s3-scality/s3-scality.conf .

%install
install -p -D -m 655 s3-scality.service $RPM_BUILD_ROOT/usr/lib/systemd/system/s3-scality.service
install -p -D -m 655 s3-scality.yml $RPM_BUILD_ROOT/etc/stratoscale/compose/rootfs-star/s3-scality.yml
install -p -D -m 655 s3-scality-monitor.service $RPM_BUILD_ROOT/etc/stratoscale/clustermanager/services/control/s3-scality.service
install -p -D -m 655 s3-scality.conf $RPM_BUILD_ROOT/etc/nginx/conf.d/services/s3-scality.conf

%files
/usr/lib/systemd/system/s3-scality.service
/etc/stratoscale/compose/rootfs-star/s3-scality.yml
/etc/stratoscale/clustermanager/services/control/s3-scality.service
/etc/nginx/conf.d/services/s3-scality.conf
