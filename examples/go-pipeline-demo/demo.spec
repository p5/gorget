Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package for gorget's vendor-bump/vendor transform steps
License:        MIT
URL:            https://example.com

%description
Demo package used to exercise gorget's Transform stage.

%prep
%build
%install
%files
%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
