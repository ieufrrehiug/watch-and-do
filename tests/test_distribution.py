import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_skill


class PublicDistribution(unittest.TestCase):
    def test_skill_links_are_in_the_download(self):
        files = set(package_skill.sources().values())
        for source in files:
            if source.suffix != ".md":
                continue
            for href in re.findall(r"\]\(([^\s)]+)\)", source.read_text(encoding="utf-8")):
                href = href.split("#", 1)[0]
                if href and ":" not in href and not href.startswith("/"):
                    self.assertIn((source.parent / href).resolve(), files, f"{source.name} links to {href}")

    def test_repository_zip_matches_the_published_source(self):
        if not package_skill.BUNDLE.exists():
            self.skipTest("This is an unpacked skill, with no nested distribution ZIP")
        package_skill.check(package_skill.BUNDLE, package_skill.sources())
