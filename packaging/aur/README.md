# Arch AUR Packaging

The published AUR package is:

```text
https://aur.archlinux.org/packages/plex-tui
```

This directory keeps the source copy of the package metadata:

- `PKGBUILD`
- `.SRCINFO`

## Validation

The `AUR Package` GitHub Actions workflow validates the package inside an
`archlinux:base-devel` container. It runs:

```bash
makepkg --clean --syncdeps --noconfirm --check
makepkg --printsrcinfo
namcap PKGBUILD ./*.pkg.tar.*
```

The workflow also verifies that committed `.SRCINFO` matches `PKGBUILD`.

## Publishing

After the workflow passes, copy `PKGBUILD` and `.SRCINFO` into the AUR checkout
and push:

```bash
cp packaging/aur/PKGBUILD /path/to/aur-plex-tui/PKGBUILD
cp packaging/aur/.SRCINFO /path/to/aur-plex-tui/.SRCINFO
cd /path/to/aur-plex-tui
git add PKGBUILD .SRCINFO
git commit -m "Update to X.Y.Z-1"
git push
```

The package depends on `mpv` because playback is delegated to the system player.
