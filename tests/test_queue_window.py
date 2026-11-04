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
