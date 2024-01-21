import os
import re
import sublime
import sublime_plugin
import errno

TMP_FILE = "/dev/shm/.sublime/gramma"


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def safe_open_w(path):
    mkdir_p(os.path.dirname(path))
    return open(path, "w")


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
        if self.is_running or not self.panel:
            return

        self.is_running = True
        text = self._get_selection()

        # For docstring, remove ":param xxx:"
        text = re.sub(r":param \w+(\s+\w+)?:", "parameter", text)
        text = text.replace("'", "")
        text = re.sub(r"[\s\n]+", " ", text, flags=re.DOTALL).strip()

        with safe_open_w(TMP_FILE) as file:
            file.write(text)

        cmd = "/usr/local/bin/gramma check -p -m -n -d casing %s" % TMP_FILE
        result = os.popen(cmd).read()
        if result.count("\n") == 3:
            result = "No error"
        else:
            result = result.split("---------------------------------", 1)[1].strip()

        self._set_text(result)
        self.view.window().run_command("show_panel", {"panel": "output.gramma_result"})
        self.is_running = False
