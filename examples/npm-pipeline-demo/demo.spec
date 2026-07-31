Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package with npm frontend

License:        MIT
Source0:        demo-1.0.0.tar.gz
Source1:        demo-npm-cache.tar.bz2
Source2:        bundled-npm-provides.inc

BuildRequires:  nodejs

# Import generated bundled npm Provides from the .inc file.
# gorget's bundled-provides post step writes this file automatically.
%include %{S:2}

%description
Demo package showing gorget's npm vendor pipeline with multi-arch
cache, vendor-bump, and bundled-provides.

%prep
%autosetup
tar -xf %{S:1}

%build
cd ui && npm ci --offline --cache "$PWD/../.npm-cache"
cd ui && npm run build

%install
install -D -p -m 0644 ui/dist/index.html %{buildroot}%{_datadir}/demo/index.html

%files
%{_datadir}/demo/index.html

%changelog
%autochangelog
