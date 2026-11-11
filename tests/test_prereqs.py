# wow-completionist-data :: tests/test_prereqs.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
"""The `previous`-field parser on shapes taken from real Warcraft Wiki quest pages."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cgdata.prereqs import lead_breadcrumb, parse_previous  # noqa: E402


def shape(field):
    r = parse_previous(field)
    return r["basis"], [(g["class"], [t for t, _f in g["titles"]]) for g in r["groups"]]


class PreviousField(unittest.TestCase):
    def test_single(self):
        self.assertEqual(shape("[[Report to Goldshire]]"), ("single", [("required", ["Report to Goldshire"])]))

    def test_none(self):
        self.assertEqual(shape(""), ("none", []))
        self.assertEqual(shape("Tillers {{rep|Honored}}"), ("none", []))

    def test_all_of_commas_and(self):
        b, g = shape("[[To Kill With Purpose (Classic)]], [[Un-Life's Little Annoyances]], and [[The Ranger Lord's Behest]]")
        self.assertEqual(b, "explicit")
        self.assertEqual([x[1] for x in g], [["To Kill With Purpose (Classic)"], ["Un-Life's Little Annoyances"],
                                             ["The Ranger Lord's Behest"]])

    def test_any_of_or(self):
        self.assertEqual(shape("[[Dressing Down]] or [[Suit Up!]]"),
                         ("explicit", [("required", ["Dressing Down", "Suit Up!"])]))
        b, g = shape("[[A]], [[B]], [[C]], or [[D]]")
        self.assertEqual(g, [("required", ["A", "B", "C", "D"])])

    def test_one_of_header(self):
        b, g = shape("at least one of:\n[[Smelt On, Smelt Off]],\n[[The Great Silver Deceiver]],\n[[The Art of the Imbue]]")
        self.assertEqual(g, [("required", ["Smelt On, Smelt Off", "The Great Silver Deceiver", "The Art of the Imbue"])])

    def test_slash_binds_tighter_than_comma(self):
        b, g = shape("[[Good-bye, Sweet Oil]], [[What Kind of Name is Chip, Anyway?]] / [[The Fastest Way to His Heart]]")
        self.assertEqual(g, [("required", ["Good-bye, Sweet Oil"]),
                             ("required", ["What Kind of Name is Chip, Anyway?", "The Fastest Way to His Heart"])])

    def test_qualifiers(self):
        self.assertEqual(shape("[[Incoming...]] (optional)<br />[[Domination Point (quest)]] (required)"),
                         ("list", [("optional", ["Incoming..."]), ("required", ["Domination Point (quest)"])]))
        self.assertEqual(shape("[[Hero's Call: Badlands!]] or [[Warchief's Command: Badlands!]] (both optional)"),
                         ("explicit", [("optional", ["Hero's Call: Badlands!", "Warchief's Command: Badlands!"])]))
        self.assertEqual(shape("[[Whelgar's Retreat (quest)]] ''(breadcrumb)''"),
                         ("single", [("breadcrumb", ["Whelgar's Retreat (quest)"])]))
        self.assertEqual(shape("[[A]] or [[B (quest)]] (optional breadcrumbs)"),
                         ("explicit", [("breadcrumb", ["A", "B (quest)"])]))
        self.assertEqual(shape("[[Advancing the Effort]], [[A Message from the Justicar]] (optional breadcrumb)"),
                         ("explicit", [("required", ["Advancing the Effort"]),
                                       ("breadcrumb", ["A Message from the Justicar"])]))
        self.assertEqual(shape("[[Simmer Down Now]] (in-progress)"), ("single", [("in_progress", ["Simmer Down Now"])]))

    def test_line_breaks_are_ambiguous_all_of(self):
        self.assertEqual(shape("[[Conservation of Magic]]<br />[[Invasive Species]]"),
                         ("list", [("required", ["Conservation of Magic"]), ("required", ["Invasive Species"])]))

    def test_faction_pairs(self):
        r = parse_previous("{{Alliance}} [[Call of the Packmaster]]<br />{{Horde}} [[The Soul of the Horde]]")
        self.assertEqual(len(r["groups"]), 1)
        self.assertEqual(r["groups"][0]["titles"], [("Call of the Packmaster", "Alliance"),
                                                     ("The Soul of the Horde", "Horde")])
        r = parse_previous("{{Alliance}} [[A]] & [[B]]<br> {{Horde}} [[C]]")
        facs = [[f for _t, f in g["titles"]] for g in r["groups"]]
        self.assertEqual(facs, [["Alliance"], ["Alliance", "Horde"]])

    def test_plainlist_and_badges(self):
        self.assertEqual(shape("{{plainlist|\n*[[Looming Shadows]],\n*[[Reports Returned]], or\n*[[The Journey Ends]]}}"),
                         ("explicit", [("required", ["Looming Shadows", "Reports Returned", "The Journey Ends"])]))
        self.assertEqual(shape("[[Return to Quinn]] / [[Return to Quinn (Again)]] ({{Forever-inline}})"),
                         ("explicit", [("required", ["Return to Quinn", "Return to Quinn (Again)"])]))

    def test_link_normalisation(self):
        self.assertEqual(shape("[[report_to goldshire|Report]]")[1], [("required", ["Report to goldshire"])])
        self.assertEqual(shape("[[File:X.png]] [[Category:Quests]] [[A]]")[1], [("required", ["A"])])


class LeadBreadcrumb(unittest.TestCase):
    def test_self_description(self):
        self.assertEqual(lead_breadcrumb("'''A Concerned Friend''' is an optional breadcrumb to the chapter"), "optional")
        self.assertEqual(lead_breadcrumb("'''The Lunar Festival''' is a [[breadcrumb]] for the chain."), "yes")
        self.assertEqual(lead_breadcrumb("[[File:X.jpg|thumb|a [[b]]]] '''Assault on Bash'ir Landing''' is a very "
                                         "quick breadcrumb quest"), "yes")
        self.assertEqual(lead_breadcrumb("{{Classic only}}\n'''Wars on Two Fronts''' was a [[breadcrumb quest]]"), "yes")

    def test_other_sentences_do_not_count(self):
        self.assertIsNone(lead_breadcrumb("'''Winter's Sigil''' concludes the chapter, though there is a breadcrumb"))
        self.assertIsNone(lead_breadcrumb("The quest '''Well Armed''' is part of it. This is a breadcrumb quest."))
        self.assertIsNone(lead_breadcrumb(""))


if __name__ == "__main__":
    unittest.main()
