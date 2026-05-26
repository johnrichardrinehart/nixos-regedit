import unittest

from nixos_regedit.tree import build_tree, option_segments


class TreeTests(unittest.TestCase):
    def test_uses_loc_when_available(self):
        option = {"loc": ["services", "demo", "enable"]}
        self.assertEqual(option_segments("ignored.key", option), ["services", "demo", "enable"])

    def test_preserves_placeholder_segments(self):
        option = {"loc": ["fileSystems", "<name>", "options"]}
        tree = build_tree({"fileSystems.<name>.options": option})
        file_systems = tree["children"][0]
        self.assertEqual(file_systems["name"], "fileSystems")
        self.assertEqual(file_systems["children"][0]["name"], "<name>")

    def test_falls_back_to_key_split(self):
        tree = build_tree({"programs.zsh.enable": {}})
        self.assertEqual(tree["children"][0]["path"], "programs")
        self.assertEqual(tree["children"][0]["children"][0]["path"], "programs.zsh")
        self.assertEqual(tree["children"][0]["children"][0]["children"], [])
        self.assertEqual(tree["children"][0]["children"][0]["optionKeys"], ["programs.zsh.enable"])


if __name__ == "__main__":
    unittest.main()
