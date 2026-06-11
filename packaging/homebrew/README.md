# Homebrew Packaging

Homebrew packaging should come after PyPI publishing is working. The formula can
then install `plex-tui` into a virtualenv and declare the external player:

```ruby
depends_on "mpv"
depends_on "python@3.13"
```

Expected formula checks:

```ruby
test do
  assert_match "plex-tui", shell_output("#{bin}/plex-tui --version")
  assert_match "plex-tui smoke ok", shell_output("#{bin}/plex-tui --smoke")
end
```

Use a tap such as `so1omon563/homebrew-plex-tui` once the PyPI package exists.
