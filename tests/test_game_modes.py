import unittest
from collections import Counter

from sim import Sim
import game_engine

RED = (255, 0, 0)
ORANGE = (255, 140, 0)


def new_time_attack(nodes, seed=1, **kw):
    sim = Sim(nodes, seed)
    game = game_engine.TimeAttackPlus(sim.engine, **kw)
    game.start()
    sim.run_until(game, lambda: game.state == "PLAYING")
    return sim, game


class TestTimeAttackMultiNode(unittest.TestCase):
    def test_first_target_and_spawn_delay(self):
        sim, game = new_time_attack([1, 2, 3, 4, 5])
        lit = sim.engine.lit()
        self.assertEqual(len(lit), 1)
        sim.run(game, 300)
        game.on_hit(lit[0])
        self.assertEqual(sim.engine.lit(), [])
        sim.run(game, 1000)  # stage 0 spawn delay is 1.2 s
        self.assertEqual(sim.engine.lit(), [], 'spawned before the spawn delay')
        sim.run(game, 300)
        self.assertEqual(len(sim.engine.lit()), 1)

    def test_never_repeats_the_node_just_hit(self):
        sim, game = new_time_attack([1, 2, 3, 4, 5])
        last = None
        for _ in range(40):
            sim.run_until(game, lambda: sim.engine.lit())
            target = sim.engine.lit()[0]
            self.assertNotEqual(target, last)
            sim.run(game, 400)
            game.on_hit(target)
            last = target

    def test_lit_count_never_exceeds_difficulty_minimum(self):
        sim, game = new_time_attack([1, 2, 3, 4, 5, 6, 7, 8], duration_min=2, difficulty="Hard")
        while game.state == "PLAYING":
            curve = game_engine.DifficultyConfig.MIN_TARGET_CURVE["Hard"]
            self.assertLessEqual(len(sim.engine.lit()), curve[game.intensity_stage])
            lit = sim.engine.lit()
            if lit:
                sim.run(game, 300)
                if game.state == "PLAYING":
                    game.on_hit(lit[0])
            else:
                sim.run(game, 100)

    def test_spawns_are_spread_evenly_over_ten_nodes(self):
        nodes = list(range(1, 11))
        sim, game = new_time_attack(nodes, duration_min=3)
        counts = Counter()
        while game.state == "PLAYING":
            lit = sim.engine.lit()
            if lit:
                counts[lit[0]] += 1
                sim.run(game, 200)
                if game.state == "PLAYING":
                    game.on_hit(lit[0])
            else:
                sim.run(game, 100)
        self.assertEqual(set(counts), set(nodes))
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 3, counts)

    def test_single_node_comes_back_after_delay(self):
        sim, game = new_time_attack([7])
        self.assertEqual(sim.engine.lit(), [7])
        game.on_hit(7)
        sim.run(game, 1300)
        self.assertEqual(sim.engine.lit(), [7])

    def test_lost_lit_node_is_replaced(self):
        sim, game = new_time_attack([1, 2, 3])
        lit = sim.engine.lit()[0]
        sim.engine.drop_node(game, lit)
        sim.run(game, 100)
        now_lit = sim.engine.lit()
        self.assertEqual(len(now_lit), 1)
        self.assertNotEqual(now_lit[0], lit)

    def test_node_joining_mid_game_gets_used_but_not_flooded(self):
        sim, game = new_time_attack([1, 2, 3], duration_min=2)
        sim.run(game, 20000)  # existing nodes build up spawn history
        sim.engine.add_node(4)
        counts = Counter()
        while game.state == "PLAYING":
            lit = sim.engine.lit()
            if lit:
                counts[lit[0]] += 1
                sim.run(game, 200)
                if game.state == "PLAYING":
                    game.on_hit(lit[0])
            else:
                sim.run(game, 100)
        self.assertGreater(counts[4], 0)
        self.assertLess(counts[4], 2 * min(counts[1], counts[2], counts[3]) + 3, counts)

    def test_penalty_freezes_spawns_then_restores(self):
        sim, game = new_time_attack([1, 2, 3])
        lit = sim.engine.lit()[0]
        dark = next(n for n in [1, 2, 3] if n != lit)
        game.on_hit(dark)
        self.assertEqual(game.score, -15)
        self.assertEqual(sim.engine.lit(ORANGE), [1, 2, 3])
        sim.run(game, 1100)
        self.assertEqual(sim.engine.lit(), [lit])

    def test_game_ends_once(self):
        sim, game = new_time_attack([1, 2])
        sim.run(game, 61000)
        self.assertEqual(game.state, "FINISHED")
        self.assertEqual(sim.engine.game_over_calls, 1)


def new_breach(nodes, seed=3):
    sim = Sim(nodes, seed)
    game = game_engine.TheBreach(sim.engine)
    game.start()
    return sim, game


def play_level(sim, game, gap_ms=1000):
    sim.run_until(game, lambda: game.state == "PLAYING")
    for node in list(game.sequence):
        sim.run(game, gap_ms)
        game.on_hit(node)
        sim.clock.now += 200  # past the 150 ms input mask


class TestBreachMultiNode(unittest.TestCase):
    def test_sequence_has_no_back_to_back_repeats(self):
        sim, game = new_breach([1, 2, 3, 4, 5, 6])
        for _ in range(4):
            seq = game.sequence
            self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])), seq)
            play_level(sim, game)
            sim.run_until(game, lambda: game.state == "FLASH_COUNTDOWN")

    def test_level_bonus_does_not_compound(self):
        sim, game = new_breach([1, 2, 3, 4])
        play_level(sim, game)
        after_1 = game.score
        sim.run_until(game, lambda: game.state == "FLASH_COUNTDOWN")
        play_level(sim, game)
        after_2 = game.score
        # Level 1 and 2 both have 3 targets and the same timing, so each
        # level must add the same number of points
        self.assertGreater(after_1, 0)
        self.assertEqual(after_2 - after_1, after_1)

    def test_wrong_node_fails_and_ends_game(self):
        sim, game = new_breach([1, 2, 3])
        sim.run_until(game, lambda: game.state == "PLAYING")
        wrong = next(n for n in [1, 2, 3] if n != game.sequence[0])
        game.on_hit(wrong)
        self.assertEqual(game.state, "FAILED")
        sim.run(game, 2500)
        self.assertEqual(sim.engine.game_over_calls, 1)

    def test_lost_node_restarts_level_without_it(self):
        sim, game = new_breach([1, 2, 3, 4, 5])
        sim.run_until(game, lambda: game.state == "PLAYING")
        lost = game.sequence[0]
        sim.engine.drop_node(game, lost)
        self.assertEqual(game.state, "FLASH_COUNTDOWN")
        self.assertEqual(game.level, 1)
        self.assertNotIn(lost, game.sequence)
        play_level(sim, game)
        sim.run(game, 100)
        self.assertEqual(game.state, "LEVEL_COMPLETE")

    def test_no_nodes_fails_cleanly(self):
        sim, game = new_breach([1])
        sim.engine.drop_node(game, 1)
        sim.run(game, 2500)
        self.assertEqual(sim.engine.game_over_calls, 1)


if __name__ == '__main__':
    unittest.main()
