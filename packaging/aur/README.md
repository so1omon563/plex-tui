# Arch AUR Packaging

This directory contains a draft `PKGBUILD` for `plex-tui`.

Before submitting to the AUR:

```bash
makepkg --clean --syncdeps --check
makepkg --printsrcinfo > .SRCINFO
namcap PKGBUILD plex-tui-*.pkg.tar.*
```

The repository also includes an `AUR Package` GitHub Actions workflow that runs
the same build/check path inside an `archlinux:base-devel` container.

The package depends on `mpv` because playback is delegated to the system player.
If any Python dependency is unavailable in the official repositories, depend on
the matching AUR package or use PyPI packaging only until the dependency path is
clear.
