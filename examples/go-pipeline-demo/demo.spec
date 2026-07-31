Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package for gorget's vendor-bump/vendor transform steps
License:        MIT
URL:            https://example.com

# vendor-bump bumps rsc.io/quote's go.mod requirement directly in the checkout
# fetch: {git} already archived Source0 from -- gorget requires a spec patch
# replicating that change onto the real build tree, or it fails closed with a
# GorgetConfigError (see gorget/fetch/vendor/gomod_patch_sync.py). This demo
# has no real %prep/%build, so the patch is declared for gorget's check only.
Patch0:         0001-bump-quote-gomod.patch

%description
Demo package used to exercise gorget's Transform stage.

%prep
%build
%install
%files
%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
