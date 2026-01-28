
from deep_research.search_policy import PolicyConfig, SearchPolicy, SearchDepth, SearchEngine

def test_depth_override():
    # Simulate TEST mode: force basic
    config = PolicyConfig(tavily_depth_override=SearchDepth.BASIC)
    policy = SearchPolicy(config)
    
    # Get a playbook that normally has ADVANCED steps (like GENERAL_MARKET)
    playbook = policy.get_playbook("General", "normal topic")
    print(f"Playbook: {playbook.name}")
    
    for i, step in enumerate(playbook.steps):
        print(f"Step {i+1}: {step.engine.value} - {step.depth.value}")
        if step.engine == SearchEngine.TAVILY:
            assert step.depth == SearchDepth.BASIC, f"Step {i+1} should be BASIC because of override"
            
    # Simulate PRODUCTION mode: no override
    config_prod = PolicyConfig(tavily_depth_override=None)
    policy_prod = SearchPolicy(config_prod)
    playbook_prod = policy_prod.get_playbook("General", "normal topic")
    print(f"\nPRODUCTION Playbook: {playbook_prod.name}")
    has_advanced = False
    for i, step in enumerate(playbook_prod.steps):
        print(f"Step {i+1}: {step.engine.value} - {step.depth.value}")
        if step.depth == SearchDepth.ADVANCED:
            has_advanced = True
    
    assert has_advanced, "Production should have at least one ADVANCED step for GENERAL_MARKET"
    print("\n✅ Verification successful: Override works as expected.")

if __name__ == "__main__":
    test_depth_override()
