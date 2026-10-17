"""Prepare operator release metadata; never opens the production registry."""
import json
import shutil
from pathlib import Path

from app.infrastructure.prompt_registry import canonical, read_prompt, sha256, toolset_contract
from app.infrastructure.runtime_version import app_source_fingerprint
from app.infrastructure.settings import load_settings

EXPECTED_SOURCE = "p-5ec7ab435e11c9a66b4e958dae74ec2e87eeb9fc21fa9491c9387a5320de7fc0"
EXPECTED_CODE = "59a20dff98bf6c91168d589602fb39a3a3e482bf037ccee81062085f3234468b"

root = Path('/app')
settings = load_settings()
if settings.prompt_pin_version:
    raise SystemExit('PROMPT_PIN_VERSION is set; refusing operator upgrade.')
fingerprint = app_source_fingerprint()
if fingerprint != EXPECTED_CODE:
    raise SystemExit('Image source differs from verified 20261017 package; stop and inspect.')
contract = toolset_contract(root, web_search_enabled=bool(settings.tavily_api_key))
candidate_path = root / 'app/application/prompts/globex.yml'
document, _ = read_prompt(candidate_path)
spec = {
    'source_version': EXPECTED_SOURCE,
    'candidate': 'p-' + sha256(canonical({'prompts': document, 'toolset': contract})),
    'toolset_sha256': sha256(canonical(contract)),
    'app_source_sha256': fingerprint,
    'evaluation_status': 'INCOMPLETE',
    'authorization': 'Manual release requires explicit operator selection using GLOBEX_MANUAL_RELEASE=1. Paired model evaluation is incomplete; this is not a quality gate PASS.',
}
bundle = Path('/upgrade')
shutil.copyfile(candidate_path, bundle / 'candidate.yml')
(bundle / 'operator-release.json').write_bytes((json.dumps(spec, indent=2) + '\n').encode('utf-8'))
print(json.dumps({'prepared': True, 'candidate': spec['candidate'], 'web_search_enabled': bool(settings.tavily_api_key), 'evaluation_status': 'INCOMPLETE'}))
