# Gramma
Grammar checker for sublime text.

# Installation
Go to the directory `Packages`, in the configuration directory of sublime, and git clone this repo.

Install Language Tool
> docker pull erikvl87/languagetool

> docker run  --detach --restart always -it -p 8010:8010 erikvl87/languagetool

# Usage
Select the text you want to verify and press CTRL + G.

Or click on the line you want to verify and press CTRL + G.

# Keybinding

Key binding example,
```json
{ "keys": ["ctrl+g"], "command": "gramma"},
```
