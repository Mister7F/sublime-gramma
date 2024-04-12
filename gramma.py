import sublime
import requests
import sublime_plugin
from functools import lru_cache
import string
import threading
import os
import random
import time
import re


zero_width = "\u200B"

to_clean_quotes = ['"', "'", "`"]

to_clean = {
    "*": {
        # (match, char) to fill
        "words": [("%s", " "), ("%i", " "), ("%r", " ")],
        "regex": [
            # code example "`F(x)`"
            (r"`(.*?)`", zero_width),
            # code example ">>> print('Hello world')"
            (r"(^|\n)(\s|%s)*>>>\s\S.*" % zero_width, " "),
            (r"\bhttp(s)?:\/\/(\w|[-./?=#])+", " "),  # urn
            (r"(\.?\/?)(([\w-])+\/)+([\w-])*", " "),  # path
        ],
    },
    "source.python": {
        "words": [(":rtype:", ".")],
        "regex": [
            (r"^#", zero_width),  # python comment
            (r":param ([\w_])+:", "."),  # docstring
        ],
    },
    "source.js": {
        "regex": [
            (r"^\/\*{2}", zero_width),  # JS comment
            (r"^\/\/", zero_width),  # JS comment
            (r"(^|\n)\s*\*\/", zero_width),  # JS comment
            (r"(^|\n)\s*\*", zero_width),  # JS comment
        ],
    },
}


to_ignore = {"UPPERCASE_SENTENCE_START", "WHITESPACE_RULE", "ARROWS"}


# additional words to add


whitelist = set()


def plugin_loaded():
    global whitelist
    settings = sublime.load_settings("Preferences.sublime-settings")
    whitelist = set(settings.get("added_words") or ())
    whitelist |= set(settings.get("ignored_words") or ())


class GrammaCommand(sublime_plugin.TextCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        w = self.view.window()
        if not w:
            self.panel = None
            return
        self.panel = w.create_output_panel("gramma_result", unlisted=True)
        self.panel.settings().set("gutter", False)
        self.panel.settings().set("scroll_past_end", False)
        self.panel.settings().set("margin", 10)
        self.is_running = False
        self.re_run = False
        # store a hash of the content of each region to know if it should be updater or not
        self.regions = {}

    def _get_selection(self):
        selection = "\n".join(self.view.substr(sel) for sel in self.view.sel())
        if selection:
            return selection
        return self.view.substr(self.view.line(self.view.sel()[0]))  # current line

    def _set_text(self, text):
        self.panel.set_read_only(False)
        self.panel.run_command("select_all")
        self.panel.run_command("right_delete")
        self.panel.run_command("append", {"characters": text})
        self.panel.set_read_only(True)

    def run(self, edit):
        self._set_text(result_to_str(language_tool(self._get_selection())))
        self.view.window().run_command("show_panel", {"panel": "output.gramma_result"})


class SublimeGramma(sublime_plugin.EventListener):
    def __init__(self):
        super().__init__()
        # allow one thread per view (0: not running, 1: running, 2: need to re-run)
        self.running = {}

    def on_activated_async(self, view):
        threading.Thread(target=_lint_file, args=(view, self.running)).start()

    def on_modified(self, view):
        threading.Thread(target=_lint_file, args=(view, self.running)).start()


def _lint_file(view, running):
    view_id = view.id()
    if running.get(view_id):
        # already running, trigger a re-run when we are done
        running[view_id] = 2
        return

    view.set_status("gramma", "Checking grammar")

    running[view_id] = 1
    error_regions = []
    annotations = []
    for region in view.find_by_selector("string, comment, text.git.commit, text.plain"):
        start, end = region.to_tuple()
        content = view.substr(region)
        scope = view.scope_name(region.a)  # source.python, source.js

        result = smart_language_tool(content, scope)

        for context, replacements, rule, start_str, size_str in result:
            error_regions.append(
                sublime.Region(start + start_str, start + start_str + size_str)
            )
            # annotations.append(trim(replacements.strip(), 20))
            # print(context, rule)

    view.add_regions(
        "gramma-reports",
        error_regions,
        icon="",
        scope="region.yellowish",
        flags=sublime.DRAW_SQUIGGLY_UNDERLINE
        | sublime.DRAW_NO_FILL
        | sublime.DRAW_NO_OUTLINE,
        annotations=annotations,
    )

    view.set_status("gramma", "")

    time.sleep(0.2)  # debounce

    re_run = running.get(view_id) == 2
    running[view_id] = 0
    if re_run:
        _lint_file(view, running)


def smart_language_tool(text, scope):
    """Skip if the text is detected as non-English (e.g. technical strings)."""
    letter_only = "".join(
        t for t in text.replace("\n", " ") if t in string.ascii_letters + " "
    ).strip()
    if len(letter_only) < 3:
        return []

    if " " not in letter_only or letter_only.count(" ") < 2:
        # let the spell check do its work
        return []

    for quote in to_clean_quotes:
        if text.startswith(quote):
            text = re.sub(r"^%s+" % quote, lambda x: "\n" * len(x.group()), text)
            text = re.sub(r"%s+$" % quote, lambda x: "\n" * len(x.group()), text)
            break

    for target_scope, items in to_clean.items():
        if target_scope != "*" and target_scope not in scope:
            continue

        for c, f in items.get("words", []):
            # important to not change the size for the parsing
            text = text.replace(c, f * len(c))

        for regex, fill in items.get("regex", []):
            text = re.sub(regex, lambda x: fill * len(x.group()), text)
    return language_tool(text)


@lru_cache(2**16)
def language_tool(text):
    # docker pull erikvl87/languagetool
    # docker run  --detach --restart always -it -p 8010:8010 erikvl87/languagetool

    # ignore missing capital letter (and still catch error for misspelling words, e.g. "bob")
    start_at = len("OK,\n")
    text = "OK,\n%s" % text

    url = "http://localhost:8010/v2/check"

    response = requests.get(url, params={"text": text, "language": "en-US"})
    if not response.ok:
        print("Error %i, %r" % (response.status_code, response.text))
        return []

    matches = [
        match
        for match in response.json().get("matches", [])
        if match["rule"]["id"] not in to_ignore
    ]

    result = []
    for match in matches:
        offset = match["offset"]
        size = match["length"]
        context = text[offset : offset + size]
        if match["type"]["typeName"] == "UnknownWord" and context in whitelist:
            # the word has been added in the whitelist
            continue

        replacements = ", ".join(r["value"] for r in match["replacements"])
        result.append((context, replacements, match["rule"], offset - start_at, size))

    return result


def result_to_str(result):
    if not result:
        return "No error"
    REPLACEMENTS_SIZE = 50

    left_size = max(len(match[0]) for match in result)
    result_str = ""
    for context, replacements, rule, *_ in result:
        result_str += context.ljust(left_size)
        result_str += " → "
        result_str += trim(replacements, REPLACEMENTS_SIZE).ljust(REPLACEMENTS_SIZE)
        result_str += " (%s)" % trim(rule["description"], 35)
        result_str += "\n"
    return result_str


def trim(string, size):
    if len(string) < size:
        return string
    return string[: size - 3] + "..."
