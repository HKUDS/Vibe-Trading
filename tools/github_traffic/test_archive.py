"""Check overlapping windows, corrections, gaps and invalid source data."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from archive import rebuild, validate


def data(rows):
    return {'count': sum(c for _, c in rows), 'uniques': 1,
            'clones': [{'timestamp': d + 'T00:00:00Z', 'count': c, 'uniques': 1} for d,c in rows]}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'snapshots').mkdir()

    def snapshot(self, name, date, rows, repo_id=123):
        (self.root/'snapshots'/name).write_text(json.dumps({
            'repository_id': repo_id, 'repository':'HKUDS/Vibe-Trading',
            'retrieved_at':date+'T12:00:00+00:00', 'data':data(rows)}))

    def rebuild(self):
        return rebuild(self.root, 123, dt.datetime(2026,11,18,tzinfo=dt.timezone.utc))

    def test_overlap_downward_revision_and_rerun(self):
        self.snapshot('z.json','2026-11-16',[('2026-11-15',100),('2026-11-16',20)])
        self.snapshot('a.json','2026-11-17',[('2026-11-15',90),('2026-11-16',40),('2026-11-17',10)])
        summary = self.rebuild()
        self.assertEqual(summary['archived_clone_count'],140)
        self.assertEqual(summary['observed_days'],3)
        self.assertEqual(self.rebuild(),summary)
        self.assertEqual(summary['latest_window_unique_cloners'],1)

    def test_gap_is_not_zero_and_later_backfill_repairs_it(self):
        self.snapshot('a.json','2026-11-17',[('2026-11-15',10),('2026-11-17',20)])
        self.assertEqual(self.rebuild()['missing_dates'],['2026-11-16'])
        self.snapshot('b.json','2026-11-18',[('2026-11-16',5),('2026-11-17',20)])
        summary=self.rebuild()
        self.assertEqual(summary['missing_dates'],[])
        self.assertEqual(summary['archived_clone_count'],35)
        self.assertFalse(summary['attention_required'])

    def test_stale_source(self):
        self.snapshot('a.json','2026-11-17',[('2026-11-10',10)])
        self.assertTrue(self.rebuild()['attention_required'])

    def test_repository_identity_is_checked(self):
        self.snapshot('a.json','2026-11-17',[('2026-11-17',10)],repo_id=999)
        with self.assertRaises(ValueError): self.rebuild()

    def test_invalid_response_does_not_replace_summary(self):
        self.snapshot('a.json','2026-11-17',[('2026-11-17',10)])
        self.rebuild()
        before=(self.root/'summary.json').read_bytes()
        broken=data([('2026-11-17',20)])
        broken['count']=21
        with self.assertRaises(ValueError): validate(broken)
        self.assertEqual((self.root/'summary.json').read_bytes(),before)

    def test_duplicate_day_is_rejected(self):
        with self.assertRaises(ValueError): validate(data([('2026-11-17',10),('2026-11-17',20)]))


if __name__=='__main__': unittest.main()
