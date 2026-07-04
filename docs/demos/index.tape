# Index demo: one-shot scan + hash with an exclude filter, then the
# sidecar manifest. Rendered against the real CLI by docs.yml.
Output docs/assets/index.gif
Require dirindex
Set Shell "bash"
Set FontSize 15
Set Width 1000
Set Height 560
Set Padding 16
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

Type "dirindex index demo -x tmp,log -o index.parquet"
Enter
Sleep 5s
Type "cat index.meta.json"
Enter
Sleep 5s
