# Scan demo: enumerate a tree, whitelist extensions, peek at the output.
# Rendered against the real CLI by .github/workflows/docs.yml.
Output docs/assets/scan.gif
Require dirindex
Set Shell "bash"
Set FontSize 15
Set Width 1000
Set Height 560
Set Padding 16
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

Type "dirindex scan demo -o everything.parquet"
Enter
Sleep 2.5s
Type "dirindex scan demo -i jpg,png -o photos.csv"
Enter
Sleep 2.5s
Type "head -n 4 photos.csv"
Enter
Sleep 4s
