Name:           demo-ui
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package for gorget's bundled-provides post step
License:        MIT
URL:            https://example.com

# The bundled-provides post step generates bundled-npm-provides.inc alongside
# this spec. In a real package you'd declare it as a SourceN: and pull it in
# with %include, so the bundled Provides show up in the built RPM's metadata:
#
#   Source1:        bundled-npm-provides.inc
#   %include %{S:1}
#
# It's left commented here so the demo runs without a full rpmbuild -- inspect
# the generated bundled-npm-provides.inc after the run instead.

%description
Demo package used to exercise gorget's bundled-provides post primitive.

%prep
%build
%install
%files
%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
