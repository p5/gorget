Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package for the Maven source pipeline
License:        MIT
URL:            https://example.com
Source0:        demo-%{version}.tar.gz
Source1:        demo-%{version}-vendor.tar.gz

%description
Demo package for Maven dependency bumps and offline vendoring.

%prep
%autosetup -n %{name}-%{version}
tar xf %{SOURCE1}

%build
mvn -o -Dmaven.repo.local=vendor package

%install

%files

%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
