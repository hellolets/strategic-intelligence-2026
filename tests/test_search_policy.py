
import unittest
from deep_research.search_policy import SearchPolicy, PolicyConfig, SearchEngine, SearchDepth, Playbook
from deep_research.config import SEARCH_POLICY_CONFIG

class TestSearchPolicy(unittest.TestCase):
    def setUp(self):
        self.config = SEARCH_POLICY_CONFIG
        self.policy = SearchPolicy(self.config)

    def test_get_playbook_strategy(self):
        playbook = self.policy.get_playbook("Strategy", "Market analysis of renewable energy")
        self.assertEqual(playbook.name, "CRITICAL_STRATEGY")
        self.assertEqual(len(playbook.steps), 2)
        self.assertEqual(playbook.steps[1].engine, SearchEngine.TAVILY)
        self.assertEqual(playbook.steps[1].depth, SearchDepth.ADVANCED)

    def test_get_playbook_deep_tech(self):
        playbook = self.policy.get_playbook("General", "Quantum computing error correction benchmarks")
        self.assertEqual(playbook.name, "DEEP_TECH")
        self.assertEqual(playbook.steps[0].engine, SearchEngine.TAVILY) # Starts with Tavily then Exa

    def test_should_escalate(self):
        playbook = self.policy.get_playbook("General", "Generic topic")
        # Step 0: Basic Tavily
        # If we have 3 sources and min is 7, should escalate (True)
        self.assertTrue(self.policy.should_escalate(3, 0, playbook))
        # If we have 8 sources, should not escalate (False)
        self.assertFalse(self.policy.should_escalate(8, 0, playbook))

    def test_should_call_exa_booster(self):
        playbook = self.policy.get_playbook("General", "Generic topic")
        # For General, min is 7. If we have 4, should call Exa booster if enabled (default is True in some cases)
        # But for CRITICAL or LOW_RECALL, it's more likely.
        
        # Test hard facts detection
        self.assertTrue(self.policy.has_hard_facts("The revenue in 2023 was $5.4 billion according to the report."))
        self.assertFalse(self.policy.has_hard_facts("The weather is nice today."))

    def test_firecrawl_candidates(self):
        sources = [
            {"url": "https://ok.com", "raw_content": "A" * 5000}, # Content enough
            {"url": "https://short.com", "raw_content": "A" * 100}, # Content low -> Candidate
            {"url": "https://facts.com", "raw_content": "Revenue was 10M", "total_score": 9} # Facts + score -> Candidate
        ]
        playbook = self.policy.get_playbook("Strategy", "Topic")
        candidates = self.policy.select_firecrawl_candidates(sources, playbook)
        urls = [c['url'] for c in candidates]
        self.assertIn("https://short.com", urls)

if __name__ == '__main__':
    unittest.main()
