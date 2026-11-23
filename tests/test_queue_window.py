import unittest
from arena_skill_timing import release,forecast

class QueueWindowTests(unittest.TestCase):
    def test_half_second_inclusive_without_early_or_transitive_release(self):
        entries=[dict(actor=str(i),end=t) for i,t in enumerate((2.,2.5,2.51,2.99))]
        q=dict(time=0,pending=entries[:])
        self.assertEqual(release(q),entries[:2]);self.assertEqual(q['time'],2.5)
        self.assertEqual(q['pending'],entries[2:])
    def test_forecast_agrees_with_boundary(self):
        self.assertEqual(forecast(0,2,2.5)['outcome'],'together')
        self.assertEqual(forecast(0,2,2.501)['outcome'],'before')
        self.assertEqual(forecast(0,2.6,2)['outcome'],'after')

    def test_allied_window_stops_at_rival_and_sorts_by_completion(self):
        first, ally, rival, later = (dict(actor=key, end=t) for key,t in (
            ('m1', 2), ('m2', 2.15), ('player', 2.25), ('m3', 2.4)))
        q = dict(time=0, pending=[later, rival, ally, first])
        team = lambda key: key == 'player'
        self.assertEqual(release(q, team=team), [first, ally])
        self.assertEqual(q['time'], 2.15)
        self.assertEqual(release(q, team=team), [rival])
        self.assertEqual(q['pending'], [later])

    def test_opposing_casts_share_only_an_exact_tie(self):
        a, b, c = [dict(actor=key, end=t) for key,t in (('a', 2), ('b', 2), ('c', 2.1))]
        q = dict(time=0, pending=[c, a, b])
        self.assertEqual(release(q, team=lambda key: key == 'b'), [a, b])
        self.assertEqual(forecast(0, 2, 2.25, window=0)['outcome'], 'before')
        self.assertEqual(forecast(0, 2, 2, window=0)['outcome'], 'together')
