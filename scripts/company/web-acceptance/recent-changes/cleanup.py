"""Explicit opt-in cleanup, after independent acceptance. Never deletes evidence."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import load_environment
p = argparse.ArgumentParser()
p.add_argument('--apply', action='store_true')
p.add_argument('--preflight-output', default='cleanup-preflight.json')
a = p.parse_args()
root = Path('artifacts/recent-changes-regression')
paths = [root/'private/environment.json', root/'faults/environment.json', root/'faults/migration/environment.json']
owned = [load_environment(path) for path in paths]
m, private = owned[0]
project = 'spec080-' + m['runId'][:12]
resources = json.loads((root/'resources.json').read_text())
plan = {'schemas': [v[0]['schema'] for v in owned], 'processes': resources['processes'], 'composeProject': project, 'redis': project+'-redis', 'imageTagsToCheck': resources['imageRecords'], 'evidenceRetained': str(root)}
print(json.dumps(plan, ensure_ascii=False, indent=2))
# Every ownership check completes before the first signal or destructive call.
# Never serialize Config.Env or full inspect responses: they contain credentials.
def docker_json(*args):
    return json.loads(subprocess.check_output(['docker', *args], text=True))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def preflight():
    import hashlib
    from datetime import datetime

    require(resources['runId'] == m['runId'] and resources['sandboxProject'] == project, 'Run identity mismatch')
    proof = resources['composeOwnership']
    expected_ids = {c['id'] for c in proof['containers']}
    actual_ids = set(subprocess.check_output(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project], text=True).split())
    require(actual_ids == expected_ids, 'Compose container inventory changed')
    process_results = []
    for process in resources['processes']:
        check = subprocess.run(['ps', '-p', str(process['pid']), '-o', 'command='], capture_output=True, text=True)
        require(check.returncode != 0 or check.stdout.strip() == process['expectedCommand'], 'Process ownership changed; refusing all cleanup')
        process_results.append({'pid': process['pid'], 'state': 'absent' if check.returncode else 'exact_command_match'})
    containers = []
    network_name = proof['network']['Name']
    require(network_name == project + '_sandbox', 'Unexpected network name')
    for expected in proof['containers']:
        item = docker_json('inspect', expected['id'])[0]
        labels = item['Config']['Labels']
        require(item['Name'] == '/' + expected['name'] and item['Created'] == expected['created'], 'Container name/creation identity changed')
        require(item['Image'] == expected['imageId'], 'Container image changed')
        require(labels == expected['labels'] and labels['com.docker.compose.project'] == project and labels['com.docker.compose.service'] == expected['service'], 'Container labels changed')
        require(labels['com.docker.compose.project.config_files'] == str(Path('deploy/company/compose.sandbox-local.yml').resolve()), 'Compose source path changed')
        require(expected['imageId'] == next(i['id'] for i in resources['imageRecords'] if i['tag'] == project + '-' + expected['service'] + ':dev'), 'Image not in original resource list')
        log = root / expected['creationEvidence']
        require(hashlib.sha256(log.read_bytes()).hexdigest() == expected['creationEvidenceSha256'], 'Creation evidence changed')
        require('Container ' + expected['name'] + ' Created' in log.read_text(), 'Missing original creation event')
        created = datetime.fromisoformat(item['Created'][:26] + '+00:00').timestamp()
        require(0 <= expected['creationLogMtime'] - created <= 5, 'Creation time differs from original event')
        mounts = {v['Name']: v['Destination'] for v in item['Mounts'] if v['Type'] == 'volume'}
        require(len(mounts) == len(item['Mounts']) and mounts == expected['mounts'], 'Container mounts changed')
        require(set(item['NetworkSettings']['Networks']) == {network_name}, 'Container networks changed')
        require(item['NetworkSettings']['Networks'][network_name]['NetworkID'] == proof['network']['Id'], 'Container network identity changed')
        containers.append({'id': item['Id'], 'name': item['Name'], 'imageId': item['Image'], 'labels': labels, 'mounts': mounts, 'created': item['Created']})
    actual_networks = set(subprocess.check_output(['docker', 'network', 'ls', '-q', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project], text=True).split())
    require(actual_networks == {proof['network']['Id']}, 'Network inventory changed')
    network = docker_json('network', 'inspect', network_name)[0]
    require(all(network[k] == proof['network'][k] for k in proof['network']), 'Network identity/labels changed')
    require(network['Labels']['com.docker.compose.project'] == project and network['Labels']['com.docker.compose.network'] == 'sandbox', 'Unexpected network labels')
    require(set(network['Containers']) <= expected_ids, 'Unowned network endpoint')
    runtime_proof = next(c for c in proof['containers'] if c['service'] == 'runtime')
    require('Network ' + network_name + ' Created' in (root / runtime_proof['creationEvidence']).read_text(), 'Missing network creation event')
    network_created = datetime.fromisoformat(network['Created'][:26] + '+00:00').timestamp()
    require(0 <= runtime_proof['creationLogMtime'] - network_created <= 5, 'Network creation time mismatch')
    volumes = docker_json('volume', 'inspect', *resources['volumes'])
    require({v['Name'] for v in proof['volumes']} == set(resources['volumes']), 'Volume inventory mismatch')
    actual_volumes = set(subprocess.check_output(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project], text=True).split())
    require(actual_volumes == set(resources['volumes']), 'Volume project inventory changed')
    for volume in volumes:
        expected = next(v for v in proof['volumes'] if v['Name'] == volume['Name'])
        require(all(volume[k] == expected[k] for k in expected), 'Volume identity/labels changed')
        require(volume['Labels']['com.docker.compose.project'] == project and volume['Labels']['com.docker.compose.volume'] == volume['Name'][len(project) + 1:], 'Unexpected volume labels')
        users = set(subprocess.check_output(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'volume=' + volume['Name']], text=True).split())
        require(users <= expected_ids, 'Volume used by unowned container')
        service = 'control' if volume['Name'].endswith('_control-state') else 'runtime'
        creation = next(c for c in proof['containers'] if c['service'] == service)
        require('Volume ' + volume['Name'] + ' Created' in (root / creation['creationEvidence']).read_text(), 'Missing volume creation event')
        volume_created = datetime.fromisoformat(volume['CreatedAt'].replace('Z', '+00:00')).timestamp()
        require(0 <= creation['creationLogMtime'] - volume_created <= 5, 'Volume creation time mismatch')
    redis = docker_json('inspect', resources['redisName'])[0]
    require(redis['Id'].startswith(resources['redisContainerId']) and redis['Name'] == '/' + project + '-redis', 'Redis ownership changed')
    for image in resources['imageRecords']:
        require(docker_json('image', 'inspect', image['tag'])[0]['Id'] == image['id'], 'Recorded image tag identity changed')
    return {'state': 'PASS', 'applyRequested': a.apply, 'cleanupExecuted': False, 'project': project, 'processes': process_results, 'schemas': plan['schemas'], 'containers': containers, 'network': proof['network'], 'volumes': proof['volumes'], 'redis': {'id': redis['Id'], 'name': redis['Name']}, 'imageIds': resources['imageRecords'], 'provenance': proof['recordedDuring']}


try:
    preflight_result = preflight()
except Exception as error:
    preflight_result = {'state': 'FAIL', 'cleanupExecuted': False, 'error': str(error), 'project': project}
    with (root / a.preflight_output).open('x') as output:
        json.dump(preflight_result, output, ensure_ascii=False, indent=2)
    raise
with (root / a.preflight_output).open('x') as output:
    json.dump(preflight_result, output, ensure_ascii=False, indent=2)
print(json.dumps({'preflight': preflight_result['state'], 'evidence': a.preflight_output, 'cleanupExecuted': False}))

if not a.apply:
    raise SystemExit(0)
for process in resources['processes']:
    pid = process['pid']
    check = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
    if not check.returncode:
        if check.stdout.strip() != process['expectedCommand']:
            raise RuntimeError('Process ownership changed; refusing to signal')
        os.kill(pid, signal.SIGTERM)
env = {**os.environ, 'LOCAL_SANDBOX_PROJECT': project, 'PAA_SANDBOX_TOKEN': private['environment']['PAA_SANDBOX_TOKEN'], 'PAA_SANDBOX_LOCAL_PORT': '8028'}
subprocess.run(['docker','compose','-p',project,'-f','deploy/company/compose.sandbox-local.yml','down','-v'], env=env, check=True)
container = subprocess.run(['docker','inspect','--format','{{.Id}}',project+'-redis'],capture_output=True,text=True)
if not container.returncode:
    if not container.stdout.strip().startswith(resources['redisContainerId']):
        raise RuntimeError('Redis ownership changed')
    subprocess.run(['docker','rm','-f',project+'-redis'],check=True)
for path in paths:
    subprocess.run([sys.executable,'scripts/company/web-acceptance/environment.py','cleanup','--metadata',str(path)],check=True)
# Remove only run-created tags, never force/prune or remove a shared original tag.
image_results = []
container_ids = subprocess.check_output(['docker','ps','-aq'],text=True).split()
containers = json.loads(subprocess.check_output(['docker','inspect',*container_ids])) if container_ids else []
for image in resources['imageRecords']:
    tag = image['tag']
    inspected = subprocess.run(['docker','image','inspect',tag],capture_output=True,text=True)
    if inspected.returncode:
        image_results.append({'tag':tag,'state':'already_absent'})
        continue
    if json.loads(inspected.stdout)[0]['Id'] != image['id']:
        image_results.append({'tag':tag,'state':'retained_changed_identity'})
        continue
    users = [c['Name'] for c in containers if c['Image'] == image['id']]
    if users:
        image_results.append({'tag':tag,'state':'retained_external_container_use','containers':users})
        continue
    removed = subprocess.run(['docker','image','rm',tag],capture_output=True,text=True)
    image_results.append({'tag':tag,'state':'removed' if removed.returncode == 0 else 'retained_docker_refusal'})
(root/'cleanup-image-results.json').write_text(json.dumps(image_results,ensure_ascii=False,indent=2))
