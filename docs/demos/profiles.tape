# Profiles demo: save a preset, inspect it, apply it by name.
# Rendered against the real CLI by .github/workflows/docs.yml.
Output docs/assets/profiles.gif
Require dirindex
Set Shell "bash"
Set FontSize 15
Set Width 1000
Set Height 560
Set Padding 16
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

Type "dirindex profile save photos -i jpg,png -a blake3 -f csv"
Enter
Sleep 1.5s
Type "dirindex profile list"
Enter
Sleep 1.5s
Type "dirindex profile show photos"
Enter
Sleep 2s
Type "dirindex index demo --profile photos -o gallery.csv"
Enter
Sleep 3.5s
Type "head -n 3 gallery.csv"
Enter
Sleep 4s
