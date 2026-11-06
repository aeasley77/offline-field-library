# Bundled runtimes

The SSD stores compressed platform-specific runtime packages to avoid consuming excessive space on exFAT. The launchers extract the necessary package into a per-user local cache on first launch; they do not install Python system-wide.

- Python 3.14.10 (Astral python-build-standalone release 20261026):
  - python-macos-arm64.tar.gz — Apple Silicon
  - python-macos-x86_64.tar.gz — Intel Mac
  - python-windows-x64.zip — 64-bit Windows; repacked from the upstream tar archive so built-in PowerShell can extract it
- Kiwix Tools:
  - Existing Apple Silicon server in app/bin/kiwix-serve (3.8.2)
  - kiwix-macos-x86_64.tar.gz — Intel Mac server (3.8.2)
  - kiwix-windows-x64.zip — Windows x64 server and ICU runtime files (3.8.1)

Python archive SHA-256 values:
- macOS arm64: 30a18bcb9ab75e485b4bf4e5d783dde165571e7e42c56dff47a2d2c5345183a4
- macOS x86_64: 01cedae5d4a66ac570e13cb35fa570d0e79ba8e9affd4518a5d85b6c2b98ff10
- Windows x64 upstream tar SHA-256: 98bbe6a0d798bcbad142e96e5930a330e4dc407638e898b515c51eb73a27580d
- Windows x64 bundled ZIP SHA-256: 3c9ad83e1e9b15728b99050c130153c804830aeb3802bd8b937211d7fbb1d731

Kiwix package MD5 values published by Kiwix and verified before extraction:
- Intel Mac 3.8.2: ac41fe873f3352cfcd3424f74bba053d
- Windows x64 3.8.1: 95f953f726aac8f320c7038f85785df9

Sources:
- Python: https://github.com/astral-sh/python-build-standalone/releases/tag/20261026
- Kiwix tools: https://download.kiwix.org/release/kiwix-tools/ (GPL-3.0; https://github.com/kiwix/kiwix-tools)

The Python archives include their license files. Kiwix Tools are GPL-3.0; see the license in the upstream repository. Update packages from official sources and recheck hashes during maintenance.
