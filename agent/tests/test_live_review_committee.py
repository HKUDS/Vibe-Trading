"""Final PM arithmetic and shell-free calculations from the real-review regression."""
import json

import pytest

from src.swarm.presets import build_run_from_preset
import src.swarm.worker as worker


def test_real_preset_tools_available_without_shell():
    run = build_run_from_preset('investment_committee', {'target': 'NVDA', 'market': 'US'})
    for spec in run.agents:
        registry = worker.build_swarm_registry(spec.tools, include_shell_tools=False)
        assert registry.get('bash') is None
        assert registry.get('quantlib_call') is not None
        assert registry.get('technical_indicators') is not None
        prompt = worker.build_worker_prompt(spec, {}, '', available_tools=set(registry.tool_names))
        assert 'bash python script.py' not in prompt
        result = json.loads(registry.execute('quantlib_call', {
            'action': 'call', 'module': 'risk', 'function': 'historical_var',
            'kwargs': {'returns': [-.03, .01, -.01, .02, -.02], 'confidence': .95},
        }))
        assert result['ok']
        assert result['result'] == pytest.approx(.03)


def test_mc_summary_reaches_shell_free_tool_without_large_matrix():
    from src.tools.quantlib_tool import QuantlibCallTool
    from src.quantlib.risk import monte_carlo_gbm, analyze_mc_results
    tool = QuantlibCallTool()
    args = dict(s0=100, mu=.03, sigma=.25, n_steps=63, n_paths=10000, seed=13)
    response = json.loads(tool.execute(action='call', module='risk', function='monte_carlo_summary', kwargs=args))
    assert response['ok'], response
    assert len(json.dumps(response)) < 3000
    expected = analyze_mc_results(monte_carlo_gbm(**args))
    assert response['result']['statistics'] == expected
    assert response['result']['n_paths'] == 10000
    assert response['result']['seed'] == 13
